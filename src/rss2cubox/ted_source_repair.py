"""Audit TED citations and repair missing article records, full text and analysis.

The default command only audits and queues work. --repair processes a bounded batch.
It never rewrites report prose, citation order or existing successful analysis.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from functools import partial
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
import uuid

import anyio
from dotenv import load_dotenv
from jsonschema import validate
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import requests

from rss2cubox.agent_sdk_runner import safe_sdk_error
from rss2cubox.config import cfg
from rss2cubox.fulltext_fetcher import FetchResult, fetch_full_text
from rss2cubox.prompt_registry import get
from rss2cubox.sync_pipeline import _normalize_url, stable_id

ROOT = Path(__file__).resolve().parents[2]
JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ted_source_jobs (
  issue_id UUID NOT NULL REFERENCES ted_issues(id) ON DELETE CASCADE,
  source_url TEXT NOT NULL,
  source JSONB NOT NULL,
  missing TEXT[] NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending','running','complete','failed')),
  record_kind TEXT,
  record_id TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  next_retry_at TIMESTAMPTZ,
  checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (issue_id,source_url)
);
"""


def source_key(url: str) -> str:
    return _normalize_url(url).rstrip('/')


def report_sources(report: dict[str, Any]) -> list[dict[str, Any]]:
    sources = {}
    for topic in report['topics']:
        for source in topic['sources']:
            url = source['url']
            parsed = urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('引用必须是有效的 HTTP(S) 原文链接。')
            sources.setdefault(source_key(url), {key: source.get(key) for key in (
                'id', 'kind', 'title', 'url', 'publisher', 'published_at', 'date_basis',
            )})
    return list(sources.values())


def has_analysis(row: dict[str, Any], kind: str = 'article') -> bool:
    keys = ('reason', 'hidden_signal', 'actionable', 'prediction') if kind == 'article' else ('ai_relevance_reason', 'summary', 'source_quote')
    return bool((kind == 'article' or row.get('enriched_at')) and any(str(row.get(key) or '').strip() for key in keys))


def find_record(conn: psycopg.Connection, source: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    urls = list({value for url in (source['url'], _normalize_url(source['url']))
                 for value in (url, url.rstrip('/'), url.rstrip('/') + '/')})
    article = conn.execute("""SELECT * FROM articles WHERE url=ANY(%s)
      ORDER BY (COALESCE(reason,'')<>'' OR COALESCE(hidden_signal,'')<>'' OR COALESCE(actionable,'')<>'') DESC,
        updated_at DESC,id LIMIT 1""", (urls,)).fetchone()
    if article:
        return 'article', article
    policy = conn.execute('SELECT * FROM policy_documents WHERE url=ANY(%s) ORDER BY enriched_at DESC NULLS LAST,id LIMIT 1', (urls,)).fetchone()
    return ('policy', policy) if policy else (None, None)


def missing_parts(kind: str | None, row: dict[str, Any] | None) -> list[str]:
    if not row:
        return ['record', 'full_text', 'analysis']
    missing = []
    if not str(row.get('full_text') or '').strip():
        missing.append('full_text')
    if not has_analysis(row, kind or 'article'):
        missing.append('analysis')
    return missing


def audit_issue(conn: psycopg.Connection, issue_id: str) -> list[dict[str, Any]]:
    """Persist missing stages without resetting failed retries or a worker's lease."""
    uuid.UUID(issue_id)
    issue = conn.execute('SELECT draft FROM ted_issues WHERE id=%s', (issue_id,)).fetchone()
    if not issue:
        raise ValueError('当前数据库中没有这期报告；请在前端同库的服务器上执行。')
    conn.execute(JOBS_SCHEMA)
    sources = report_sources(issue['draft'])
    for source in sources:
        kind, row = find_record(conn, source)
        missing = missing_parts(kind, row)
        conn.execute("""INSERT INTO ted_source_jobs (issue_id,source_url,source,missing,status,record_kind,record_id)
          VALUES (%s,%s,%s,%s,%s,%s,%s)
          ON CONFLICT (issue_id,source_url) DO UPDATE SET
            source=EXCLUDED.source,missing=EXCLUDED.missing,record_kind=EXCLUDED.record_kind,record_id=EXCLUDED.record_id,
            status=CASE WHEN EXCLUDED.status='complete' THEN 'complete'
                        WHEN ted_source_jobs.status='complete' THEN 'pending' ELSE ted_source_jobs.status END,
            last_error=CASE WHEN EXCLUDED.status='complete' THEN NULL ELSE ted_source_jobs.last_error END,
            next_retry_at=CASE WHEN EXCLUDED.status='complete' THEN NULL ELSE ted_source_jobs.next_retry_at END,
            checked_at=now()""",
          (issue_id, source_key(source['url']), Jsonb(source), missing, 'pending' if missing else 'complete', kind, str(row['id']) if row else None))
    # Citations removed from a later report revision are not eligible for repair.
    conn.execute('DELETE FROM ted_source_jobs WHERE issue_id=%s AND NOT (source_url=ANY(%s))',
                 (issue_id, [source_key(source['url']) for source in sources]))
    conn.execute("""UPDATE ted_source_jobs SET status='failed',last_error=COALESCE(last_error,'处理进程中断，已达到3次尝试上限。'),
      next_retry_at=NULL WHERE issue_id=%s AND status='running' AND attempts>=3
        AND updated_at<now()-interval '30 minutes'""", (issue_id,))
    return conn.execute('SELECT * FROM ted_source_jobs WHERE issue_id=%s ORDER BY source_url', (issue_id,)).fetchall()


def fetch_source(source: dict[str, Any]) -> FetchResult:
    parsed = urlsplit(source['url'])
    parts = parsed.path.strip('/').split('/')
    if parsed.hostname == 'github.com' and len(parts) >= 5 and parts[2] == 'blob' and parts[-1].endswith(('.md', '.txt')):
        url = 'https://raw.githubusercontent.com/' + '/'.join(parts[:2] + parts[3:])
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        if len(response.content) > 2_000_000 or response.headers.get('content-type', '').startswith('text/html'):
            raise ValueError('仓库原始文档格式或大小不符合要求。')
        return FetchResult(text=response.content.decode('utf-8'), source='github_raw', level=1)
    return fetch_full_text(source['url'])


def ensure_article(conn: psycopg.Connection, source: dict[str, Any]) -> dict[str, Any]:
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (source_key(source['url']),))
        kind, row = find_record(conn, source)
        if row:
            if kind != 'article':
                raise ValueError('政策引用需要由政策 enrich 流程补齐。')
            return row
        if source.get('kind') == 'policy':
            raise ValueError('缺失的政策引用需要先通过政策采集流程入库。')
        article_id = stable_id({'link': source['url']})
        published = source.get('published_at') if source.get('date_basis') == 'published' else None
        conn.execute("""INSERT INTO articles
          (id,source_type,source_feed_id,source_feed_name,source_article_id,title,url,publish_time)
          VALUES (%s,%s,'ted:manual',%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
          (article_id, cfg.str('IC_SOURCE_TYPE'), source.get('publisher') or 'TED 引用补录', article_id,
           source['title'], source['url'], published))
        row = conn.execute('SELECT * FROM articles WHERE id=%s', (article_id,)).fetchone()
        if source_key(row['url']) != source_key(source['url']):
            raise ValueError('文章标识与原始链接冲突。')
        return row


def save_analysis(conn: psycopg.Connection, article_id: str, analysis: dict[str, Any]) -> None:
    """Validate the real agent result; update analysis fields only, preserving raw data."""
    schema = get('enrich').output_schema
    validate(analysis, schema)
    if analysis['content_source'] != 'full_text' or not all(analysis[key].strip() for key in ('core_event', 'reason', 'hidden_signal', 'actionable')):
        raise ValueError('补齐需要基于正文的完整分析，不能使用空结果或摘要替代。')
    if any(key not in schema['properties'] for key in analysis):
        raise ValueError('分析包含未定义字段。')
    with conn.transaction():
        row = conn.execute('SELECT * FROM articles WHERE id=%s FOR UPDATE', (article_id,)).fetchone()
        if not row or not str(row.get('full_text') or '').strip():
            raise ValueError('保存分析前必须已有文章正文。')
        if has_analysis(row):
            return
        from psycopg import sql
        values = {('description' if key == 'core_event' else key): value for key, value in analysis.items()}
        values['enrich_meta'] = {**(row.get('enrich_meta') or {}), 'ted_source_repair': {
            'status': 'complete', 'completed_at': datetime.now(timezone.utc).isoformat(),
            'prompt_version': get('enrich').version,
        }}
        assignments = sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(key)) for key in values)
        conn.execute(sql.SQL('UPDATE articles SET {},updated_at=now() WHERE id=%s').format(assignments),
                     [Jsonb(value) if isinstance(value, (dict, list)) else value for value in values.values()] + [article_id])


def log_event(level: str, event: str, **fields: Any) -> None:
    print(json.dumps({'ts': datetime.now(timezone.utc).isoformat(), 'level': level, 'event': event, **fields}, ensure_ascii=False, default=str), flush=True)


def repair_issue(conn: psycopg.Connection, issue_id: str, *, limit: int = 5, max_budget_usd: float = 1.0, urls: list[str] | None = None) -> list[dict[str, Any]]:
    jobs = audit_issue(conn, issue_id)
    selected = {source_key(url) for url in urls} if urls else None
    processed = 0
    for job in jobs:
        if not job['missing'] or (selected is not None and job['source_url'] not in selected):
            continue
        if processed >= limit:
            break
        claimed = conn.execute("""UPDATE ted_source_jobs SET status='running',attempts=attempts+1,updated_at=now()
          WHERE issue_id=%s AND source_url=%s AND attempts<3
            AND ((status IN ('pending','failed') AND (next_retry_at IS NULL OR next_retry_at<=now()))
                 OR (status='running' AND updated_at<now()-interval '30 minutes')) RETURNING attempts""",
          (issue_id, job['source_url'])).fetchone()
        if not claimed:
            continue
        processed += 1
        source = job['source']
        try:
            article = ensure_article(conn, source)
            if not str(article.get('full_text') or '').strip():
                fetched = fetch_source(source)
                if len(fetched.text.strip()) < 200:
                    raise ValueError(fetched.error or '未取得足够的原文正文。')
                conn.execute("""UPDATE articles SET full_text=%s,full_text_source=%s,full_text_fetched_at=now(),updated_at=now()
                  WHERE id=%s AND NULLIF(btrim(full_text),'') IS NULL""", (fetched.text, fetched.source, article['id']))
                article = conn.execute('SELECT * FROM articles WHERE id=%s', (article['id'],)).fetchone()
            if len(article['full_text']) > 60000:
                raise ValueError('正文超过本次完整分析上限，请分段处理后重试。')
            if not has_analysis(article):
                from rss2cubox.enrich_agent import _enrich_one
                analysis, reason = anyio.run(partial(_enrich_one,
                    {'eid': article['id'], 'title': article['title'], 'url': article['url'], 'description': article.get('description') or ''},
                    {}, log_event, pre_fetched_text=article['full_text'], full_text_max_chars=60000, max_budget_usd=max_budget_usd))
                if not analysis:
                    raise RuntimeError(reason)
                save_analysis(conn, article['id'], analysis)
            conn.execute("""UPDATE ted_source_jobs SET status='complete',missing='{}',last_error=NULL,next_retry_at=NULL,
              record_kind='article',record_id=%s,updated_at=now() WHERE issue_id=%s AND source_url=%s""",
              (article['id'], issue_id, job['source_url']))
            log_event('INFO', 'ted_source_repaired', url=source['url'], record_id=article['id'])
        except Exception as error:
            detail = safe_sdk_error(error)
            conn.execute("""UPDATE ted_source_jobs SET status='failed',last_error=%s,next_retry_at=now()+interval '15 minutes',updated_at=now()
              WHERE issue_id=%s AND source_url=%s""", (detail, issue_id, job['source_url']))
            log_event('WARN', 'ted_source_repair_failed', url=source['url'], error=detail)
            if any(term in detail.lower() for term in ('额度不足', 'insufficient', 'failed to authenticate', 'invalid_api_key')):
                break
    return audit_issue(conn, issue_id)


def audit_saved_issue(issue_id: str) -> list[dict[str, Any]]:
    try:
        with psycopg.connect(cfg.str('DATABASE_URL'), autocommit=True, row_factory=dict_row, connect_timeout=10) as conn:
            return audit_issue(conn, issue_id)
    except psycopg.Error as error:
        raise RuntimeError('引用完整性检查未完成：' + safe_sdk_error(error)) from error


def main() -> int:
    load_dotenv(ROOT / '.env', override=True)
    parser = argparse.ArgumentParser(description='TED 引用完整性检查与定向补齐')
    parser.add_argument('--issue', required=True, type=uuid.UUID)
    parser.add_argument('--repair', action='store_true', help='补录及分析缺失引用；默认只检查并入队')
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--max-budget-usd', type=float, default=1.0, help='单篇分析的 SDK 预算上限')
    parser.add_argument('--url', action='append', help='只处理指定原始链接，可重复传入')
    args = parser.parse_args()
    if not 1 <= args.limit <= 20 or not 0 < args.max_budget_usd <= 5:
        parser.error('每批需要1–20条，单篇预算需要大于0且不超过5美元。')
    try:
        with psycopg.connect(cfg.str('DATABASE_URL'), autocommit=True, row_factory=dict_row, connect_timeout=10) as conn:
            jobs = repair_issue(conn, str(args.issue), limit=args.limit, max_budget_usd=args.max_budget_usd, urls=args.url) if args.repair else audit_issue(conn, str(args.issue))
        pending = [{'url': job['source_url'], 'missing': job['missing'], 'status': job['status'], 'attempts': job['attempts'], 'error': job['last_error']} for job in jobs if job['missing']]
        print(json.dumps({'issue_id': str(args.issue), 'references': len(jobs), 'complete': len(jobs)-len(pending), 'pending': pending}, ensure_ascii=False, default=str))
        return 2 if pending else 0
    except Exception as error:
        print(json.dumps({'error': safe_sdk_error(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
