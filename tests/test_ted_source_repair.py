from pathlib import Path
import os
import uuid
from unittest.mock import AsyncMock, Mock

from dotenv import dotenv_values
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from rss2cubox import ted_source_repair as repair
from rss2cubox.fulltext_fetcher import FetchResult


def source(url='https://example.org/article'):
    return {'id': 'ref', 'kind': 'external', 'title': '官方发布', 'url': url,
            'publisher': '发布机构', 'published_at': None, 'date_basis': 'unknown'}


def analysis():
    return {'core_event': '官方发布新模型', 'reason': '发布信息值得核对', 'hidden_signal': '模型成本继续下降',
            'actionable': '用真实任务验证', 'tags': ['模型'], 'importance_score': 4, 'content_source': 'full_text',
            'signal_type': 1, 'evidence_type': 1, 'evidence_strength': 4, 'novelty_score': 3,
            'impact_horizon': 2, 'audience': [2], 'market_stage': 3, 'confidence': 4,
            'entities': ['模型'], 'cluster_hint': '模型进展', 'watch_keywords': ['开放权重'],
            'prediction': '预计继续补充运行条件', 'disconfirming_evidence': '实际运行无法复现'}


def test_deduplicates_citations_and_excludes_editorial_notes():
    first = {**source(), 'reason': '引用说明', 'analysis': {'reason': '旧快照'}}
    sources = repair.report_sources({'topics': [{'sources': [first, source(first['url']+'?utm_source=feed#top')]}]})
    assert len(sources) == 1
    assert 'analysis' not in sources[0] and 'reason' not in sources[0]
    with pytest.raises(ValueError):
        repair.report_sources({'topics': [{'sources': [source('javascript:alert(1)')]}]})


def test_reads_github_document_as_raw_markdown_without_changing_citation_url(requests_mock):
    citation = source('https://github.com/owner/repo/blob/main/doc/guide.md')
    raw = 'https://raw.githubusercontent.com/owner/repo/main/doc/guide.md'
    requests_mock.get(raw, text='# Guide\n' + 'Document content. '*40, headers={'content-type': 'text/plain'})
    result = repair.fetch_source(citation)
    assert result.source == 'github_raw' and result.text.startswith('# Guide')
    assert citation['url'].startswith('https://github.com/')


def test_repair_prompt_includes_the_end_of_long_original_documents():
    from rss2cubox.enrich_agent import _build_user_prompt
    text = '原始正文' * 7000 + '文档末尾的验证条件'
    prompt = _build_user_prompt(source(), {}, pre_fetched_text=text, full_text_max_chars=60000)
    assert '文档末尾的验证条件' in prompt


@pytest.fixture()
def database():
    root = Path(__file__).resolve().parents[1]
    url = os.environ.get('DATABASE_URL') or dotenv_values(root/'web/.env.local').get('DATABASE_URL')
    if not url:
        pytest.skip('Local PostgreSQL unavailable')
    try:
        admin = psycopg.connect(url, autocommit=True, connect_timeout=4)
    except psycopg.Error:
        pytest.skip('Local PostgreSQL unavailable')
    name = 'ted_repair_test_' + uuid.uuid4().hex
    admin.execute(f'CREATE SCHEMA {name}')
    conn = psycopg.connect(url, autocommit=True, row_factory=dict_row, options=f'-c search_path={name},public')
    try:
        conn.execute('CREATE TABLE articles (LIKE public.articles INCLUDING ALL)')
        conn.execute('CREATE TABLE policy_documents (LIKE public.policy_documents INCLUDING ALL)')
        conn.execute('CREATE TABLE ted_issues (id UUID PRIMARY KEY,draft JSONB NOT NULL)')
        yield conn
    finally:
        conn.close()
        admin.execute(f'DROP SCHEMA {name} CASCADE')
        admin.close()


def make_issue(conn, sources):
    issue_id = str(uuid.uuid4())
    conn.execute('INSERT INTO ted_issues(id,draft) VALUES (%s,%s)',
                 (issue_id, Jsonb({'topics': [{'sources': sources}]})))
    return issue_id


def test_repairs_once_and_preserves_existing_successful_analysis(database, monkeypatch):
    conn = database
    known = repair.ensure_article(conn, source('https://example.org/known'))
    conn.execute('UPDATE articles SET full_text=%s,reason=%s WHERE id=%s', ('原始正文'*100, '已有判断不可覆盖', known['id']))
    issue_id = make_issue(conn, [source('https://example.org/known'), source()])
    fetch = Mock(return_value=FetchResult(text='官方完整正文'*100, source='test'))
    enrich = AsyncMock(return_value=(analysis(), 'ok'))
    monkeypatch.setattr(repair, 'fetch_source', fetch)
    monkeypatch.setattr('rss2cubox.enrich_agent._enrich_one', enrich)
    result = repair.repair_issue(conn, issue_id)
    assert all(not job['missing'] and job['status']=='complete' for job in result)
    article = repair.find_record(conn, source())[1]
    assert article['publish_time'] is None
    assert article['reason']==analysis()['reason']
    assert article['enrich_meta']['ted_source_repair']['status']=='complete'
    assert repair.find_record(conn, source('https://example.org/known'))[1]['reason']=='已有判断不可覆盖'
    repair.repair_issue(conn, issue_id)
    assert fetch.call_count==1 and enrich.call_count==1
    assert conn.execute('SELECT count(*) AS n FROM articles').fetchone()['n']==2
    assert enrich.call_args.kwargs['full_text_max_chars']==60000


def test_failure_is_persisted_and_backoff_survives_repeated_audits(database, monkeypatch):
    conn = database
    issue_id = make_issue(conn, [source()])
    monkeypatch.setattr(repair, 'fetch_source', lambda _: FetchResult(text='完整正文'*100, source='test'))
    enrich = AsyncMock(return_value=(None, 'API Error: 403 用户额度不足'))
    monkeypatch.setattr('rss2cubox.enrich_agent._enrich_one', enrich)
    first = repair.repair_issue(conn, issue_id)[0]
    assert first['status']=='failed' and first['attempts']==1
    assert first['missing']==['analysis'] and '额度不足' in first['last_error']
    assert first['next_retry_at'] is not None
    repair.repair_issue(conn, issue_id)
    assert enrich.call_count==1
    conn.execute("UPDATE ted_source_jobs SET next_retry_at=now()-interval '1 minute' WHERE issue_id=%s", (issue_id,))
    enrich.return_value=(analysis(), 'ok')
    last = repair.repair_issue(conn, issue_id)[0]
    assert last['status']=='complete' and last['attempts']==2 and last['last_error'] is None


def test_invalid_analysis_never_marks_a_citation_complete(database, monkeypatch):
    conn = database
    issue_id = make_issue(conn, [source()])
    monkeypatch.setattr(repair, 'fetch_source', lambda _: FetchResult(text='完整正文'*100, source='test'))
    monkeypatch.setattr('rss2cubox.enrich_agent._enrich_one', AsyncMock(return_value=({**analysis(), 'importance_score': 9}, 'ok')))
    result = repair.repair_issue(conn, issue_id)[0]
    assert result['status']=='failed' and result['missing']==['analysis']
    assert not repair.has_analysis(repair.find_record(conn, source())[1])


def test_removed_citation_cannot_be_processed_and_audit_preserves_worker_lease(database):
    conn = database
    issue_id = make_issue(conn, [source()])
    repair.audit_issue(conn, issue_id)
    conn.execute("UPDATE ted_source_jobs SET status='running',updated_at=now()-interval '31 minutes' WHERE issue_id=%s", (issue_id,))
    before=conn.execute('SELECT updated_at FROM ted_source_jobs WHERE issue_id=%s', (issue_id,)).fetchone()['updated_at']
    assert repair.audit_issue(conn, issue_id)[0]['updated_at']==before
    conn.execute('UPDATE ted_issues SET draft=%s WHERE id=%s', (Jsonb({'topics': []}), issue_id))
    assert repair.audit_issue(conn, issue_id)==[]


def test_interrupted_final_attempt_becomes_failed_instead_of_staying_running(database):
    conn = database
    issue_id = make_issue(conn, [source()])
    repair.audit_issue(conn, issue_id)
    conn.execute("UPDATE ted_source_jobs SET status='running',attempts=3,updated_at=now()-interval '31 minutes' WHERE issue_id=%s", (issue_id,))
    job = repair.audit_issue(conn, issue_id)[0]
    assert job['status']=='failed' and '3次尝试上限' in job['last_error']
