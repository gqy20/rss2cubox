"""政策文件的本地存储与信源健康度记录。

两张表都独立于现有 articles / global_insights，删掉政策模块不会留下残留。

policy_source_state 是失效监测的核心：爬虫最危险的不是抓不到，而是**静默失效**
（选择器过时 → 返回 0 条 → 不报错 → 你以为最近没有新政策）。所以这里记录每个
站点的连续空跑次数，由 get_stale_sources() 供告警和 make doctor 消费。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import psycopg

from rss2cubox.db_client._base import _get_db_url
from rss2cubox.policy.engine import PolicyItem, ScrapeResult

POLICY_DOCUMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS policy_documents (
    id                VARCHAR(64) PRIMARY KEY,
    site_key          VARCHAR(64) NOT NULL,
    site_name         VARCHAR(200),
    level             VARCHAR(20),
    region            VARCHAR(60),
    title             TEXT NOT NULL,
    url               TEXT NOT NULL,
    published_at      TIMESTAMPTZ,
    raw_date          VARCHAR(40),
    first_seen_at     TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at      TIMESTAMPTZ DEFAULT NOW(),
    seen_count        INTEGER DEFAULT 1,
    -- 以下由政策 enrich 阶段回填，抓取阶段留空
    full_text         TEXT,
    full_text_fetched_at TIMESTAMPTZ,
    jurisdiction      VARCHAR(60),
    instrument_type   VARCHAR(40),
    stage             VARCHAR(30),
    effective_date    DATE,
    affected_parties  JSONB DEFAULT '[]',
    obligation_level  VARCHAR(20),
    ai_relevance      SMALLINT,
    summary           TEXT,
    source_quote      TEXT,
    enrich_meta       JSONB DEFAULT '{}',
    enriched_at       TIMESTAMPTZ,
    CONSTRAINT policy_documents_url_unique UNIQUE (url)
);

CREATE INDEX IF NOT EXISTS idx_policy_docs_site ON policy_documents(site_key);
CREATE INDEX IF NOT EXISTS idx_policy_docs_published ON policy_documents(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_policy_docs_region ON policy_documents(region);
CREATE INDEX IF NOT EXISTS idx_policy_docs_enriched ON policy_documents(enriched_at);
CREATE INDEX IF NOT EXISTS idx_policy_docs_ai_relevance ON policy_documents(ai_relevance DESC);

-- enrich 本体补充字段（沿用项目既有的增量加列模式）
ALTER TABLE policy_documents
    ADD COLUMN IF NOT EXISTS issuing_authority VARCHAR(200),
    ADD COLUMN IF NOT EXISTS document_number   VARCHAR(120),
    ADD COLUMN IF NOT EXISTS comment_deadline  DATE,
    ADD COLUMN IF NOT EXISTS key_provisions    JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS ai_relevance_reason TEXT,
    ADD COLUMN IF NOT EXISTS confidence        SMALLINT,
    ADD COLUMN IF NOT EXISTS policy_lineage    VARCHAR(60);

-- 预筛（triage）阶段：用一次 LLM 调用批量给标题打分，只让高相关的进入
-- 昂贵的逐篇 deep enrich。没有这一层，民生通知（停水/月票/招考）会和白金政策
-- 文件一起消耗同等 token。
ALTER TABLE policy_documents
    ADD COLUMN IF NOT EXISTS triaged_at        TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS triage_relevance  SMALLINT,
    ADD COLUMN IF NOT EXISTS triage_is_policy  BOOLEAN;

CREATE INDEX IF NOT EXISTS idx_policy_docs_triage ON policy_documents(triage_relevance DESC);
"""

POLICY_SOURCE_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS policy_source_state (
    site_key               VARCHAR(64) PRIMARY KEY,
    site_name              VARCHAR(200),
    level                  VARCHAR(20),
    region                 VARCHAR(60),
    last_run_at            TIMESTAMPTZ,
    last_success_at        TIMESTAMPTZ,
    last_status            VARCHAR(24),
    last_error             TEXT,
    last_item_count        INTEGER DEFAULT 0,
    last_raw_item_count    INTEGER DEFAULT 0,
    last_duration_ms       INTEGER DEFAULT 0,
    consecutive_empty_runs INTEGER DEFAULT 0,
    total_runs             INTEGER DEFAULT 0,
    total_items            INTEGER DEFAULT 0,
    updated_at             TIMESTAMPTZ DEFAULT NOW()
);
"""


def ensure_policy_schema(db_url: str | None = None) -> bool:
    db_url = _get_db_url(db_url)
    if not db_url:
        logging.warning("LOCAL_DB_URL not set, skipping policy schema")
        return False
    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(POLICY_DOCUMENTS_SCHEMA)
            cur.execute(POLICY_SOURCE_STATE_SCHEMA)
            conn.commit()
            return True
    except Exception as e:  # noqa: BLE001
        logging.warning(f"Failed to ensure policy schema: {e}")
        return False


def save_policy_documents(
    items: list[PolicyItem],
    *,
    site_name: str = "",
    level: str = "",
    region: str = "",
    db_url: str | None = None,
) -> dict[str, int]:
    """幂等写入。已存在的记录只更新 last_seen_at / seen_count / 标题，
    不覆盖 enrich 阶段回填的字段。
    """
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    db_url = _get_db_url(db_url)
    if not db_url:
        logging.warning("LOCAL_DB_URL not set, skipping policy document save")
        stats["skipped"] = len(items)
        return stats
    if not items:
        return stats

    sql = """
        INSERT INTO policy_documents
            (id, site_key, site_name, level, region, title, url, published_at, raw_date)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            last_seen_at = NOW(),
            seen_count   = policy_documents.seen_count + 1,
            title        = EXCLUDED.title,
            site_name    = EXCLUDED.site_name,
            level        = EXCLUDED.level,
            region       = EXCLUDED.region
    """
    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            existing: set[str] = set()
            ids = [item.doc_id for item in items]
            # 分批查已存在，避免超长 IN 列表
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                cur.execute(
                    "SELECT id FROM policy_documents WHERE id = ANY(%s)",
                    (chunk,),
                )
                existing.update(row[0] for row in cur.fetchall())

            for item in items:
                cur.execute(
                    sql,
                    (
                        item.doc_id,
                        item.site_key,
                        site_name,
                        level,
                        region,
                        item.title,
                        item.url,
                        item.published_at,
                        item.raw_date,
                    ),
                )
                if item.doc_id in existing:
                    stats["updated"] += 1
                else:
                    stats["inserted"] += 1
            conn.commit()
    except Exception as e:  # noqa: BLE001
        logging.warning(f"Failed to save policy documents: {e}")
        stats["skipped"] = len(items)
    return stats


def record_source_state(
    result: ScrapeResult,
    *,
    level: str = "",
    region: str = "",
    db_url: str | None = None,
) -> None:
    """记录一次抓取结果，并维护 consecutive_empty_runs。

    只有真正拿到条目才算成功并清零连续空跑计数；empty / parse_error /
    http_error / timeout 全部累加，用于触发失效告警。
    """
    db_url = _get_db_url(db_url)
    if not db_url:
        return
    got_items = len(result.items) > 0
    sql = """
        INSERT INTO policy_source_state AS s
            (site_key, site_name, level, region, last_run_at, last_success_at,
             last_status, last_error, last_item_count, last_raw_item_count,
             last_duration_ms, consecutive_empty_runs, total_runs, total_items, updated_at)
        VALUES
            (%s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s, 1, %s, NOW())
        ON CONFLICT (site_key) DO UPDATE SET
            site_name              = EXCLUDED.site_name,
            level                  = EXCLUDED.level,
            region                 = EXCLUDED.region,
            last_run_at            = NOW(),
            last_success_at        = COALESCE(EXCLUDED.last_success_at, s.last_success_at),
            last_status            = EXCLUDED.last_status,
            last_error             = EXCLUDED.last_error,
            last_item_count        = EXCLUDED.last_item_count,
            last_raw_item_count    = EXCLUDED.last_raw_item_count,
            last_duration_ms       = EXCLUDED.last_duration_ms,
            consecutive_empty_runs = CASE
                WHEN EXCLUDED.consecutive_empty_runs = 0 THEN 0
                ELSE s.consecutive_empty_runs + 1
             END,
            total_runs             = s.total_runs + 1,
            total_items            = s.total_items + EXCLUDED.total_items,
            updated_at             = NOW()
    """
    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(
                sql,
                (
                    result.site_key,
                    result.site_name,
                    level,
                    region,
                    datetime.now(timezone.utc) if got_items else None,
                    result.status,
                    result.error or None,
                    len(result.items),
                    result.raw_item_count,
                    result.duration_ms,
                    0 if got_items else 1,
                    len(result.items),
                ),
            )
            conn.commit()
    except Exception as e:  # noqa: BLE001
        logging.warning(f"Failed to record policy source state for {result.site_key}: {e}")


def get_stale_sources(
    *,
    min_empty_runs: int = 2,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    """返回连续空跑达到阈值的站点 —— 这些极可能已经静默失效。"""
    db_url = _get_db_url(db_url)
    if not db_url:
        return []
    sql = """
        SELECT site_key, site_name, level, region, last_status, last_error,
               consecutive_empty_runs, last_run_at, last_success_at, total_runs
        FROM policy_source_state
        WHERE consecutive_empty_runs >= %s
        ORDER BY consecutive_empty_runs DESC, site_key
    """
    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(sql, (min_empty_runs,))
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:  # noqa: BLE001
        logging.warning(f"Failed to query stale policy sources: {e}")
        return []


def get_source_states(db_url: str | None = None) -> list[dict[str, Any]]:
    db_url = _get_db_url(db_url)
    if not db_url:
        return []
    sql = """
        SELECT site_key, site_name, level, region, last_status, last_item_count,
               consecutive_empty_runs, last_success_at, last_error
        FROM policy_source_state ORDER BY level, region, site_key
    """
    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(sql)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:  # noqa: BLE001
        logging.warning(f"Failed to query policy source states: {e}")
        return []


def get_policy_documents(
    *,
    limit: int = 100,
    region: str | None = None,
    level: str | None = None,
    site_key: str | None = None,
    unenriched_only: bool = False,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    """供 enrich 阶段和前端 API 消费。"""
    db_url = _get_db_url(db_url)
    if not db_url:
        return []
    clauses: list[str] = []
    params: list[Any] = []
    if region:
        clauses.append("region = %s")
        params.append(region)
    if level:
        clauses.append("level = %s")
        params.append(level)
    if site_key:
        clauses.append("site_key = %s")
        params.append(site_key)
    if unenriched_only:
        clauses.append("enriched_at IS NULL")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT id, site_key, site_name, level, region, title, url, published_at,
               raw_date, first_seen_at, last_seen_at, seen_count, jurisdiction,
               instrument_type, stage, effective_date, affected_parties,
               obligation_level, ai_relevance, summary, source_quote, enriched_at,
               issuing_authority, document_number, comment_deadline,
               key_provisions, ai_relevance_reason, confidence
        FROM policy_documents
        {where}
        ORDER BY COALESCE(published_at, first_seen_at) DESC NULLS LAST, id
        LIMIT %s
    """
    params.append(max(1, int(limit)))
    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(sql, tuple(params))
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:  # noqa: BLE001
        logging.warning(f"Failed to query policy documents: {e}")
        return []


# enrich 阶段可写的列。白名单化，避免把 dict 的 key 直接拼进 SQL。
_ENRICH_COLUMNS: dict[str, str] = {
    "issuing_authority": "issuing_authority",
    "jurisdiction": "jurisdiction",
    "instrument_type": "instrument_type",
    "stage": "stage",
    "document_number": "document_number",
    "effective_date": "effective_date",
    "comment_deadline": "comment_deadline",
    "affected_parties": "affected_parties",
    "obligation_level": "obligation_level",
    "ai_relevance": "ai_relevance",
    "ai_relevance_reason": "ai_relevance_reason",
    "summary": "summary",
    "key_provisions": "key_provisions",
    "source_quote": "source_quote",
    "confidence": "confidence",
    "enrich_meta": "enrich_meta",
    "policy_lineage": "policy_lineage",
}


def get_documents_for_enrichment(
    *,
    limit: int = 50,
    site_key: str | None = None,
    level: str | None = None,
    min_title_length: int = 8,
    min_triage_relevance: int | None = None,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    """取尚未 enrich 的政策文件，按发布时间倒序（新的先处理）。

    min_triage_relevance 不为 None 时，只返回预筛打分达到该阈值的文档 ——
    这是把昂贵的逐篇 deep enrich 限制在真正相关的文档上的开关。
    """
    db_url = _get_db_url(db_url)
    if not db_url:
        return []
    clauses = ["enriched_at IS NULL", "CHAR_LENGTH(title) >= %s"]
    params: list[Any] = [max(1, int(min_title_length))]
    if min_triage_relevance is not None:
        clauses.append("triage_relevance IS NOT NULL AND triage_relevance >= %s")
        params.append(int(min_triage_relevance))
    if site_key:
        clauses.append("site_key = %s")
        params.append(site_key)
    if level:
        clauses.append("level = %s")
        params.append(level)
    params.append(max(1, int(limit)))
    sql = f"""
        SELECT id, site_key, site_name, level, region, title, url, published_at, full_text
        FROM policy_documents
        WHERE {' AND '.join(clauses)}
        ORDER BY COALESCE(published_at, first_seen_at) DESC NULLS LAST, id
        LIMIT %s
    """
    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(sql, tuple(params))
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:  # noqa: BLE001
        logging.warning(f"Failed to query policy documents for enrichment: {e}")
        return []


def save_policy_enrichment(
    doc_id: str,
    fields: dict[str, Any],
    *,
    full_text: str | None = None,
    db_url: str | None = None,
) -> bool:
    """回写 enrich 结果。只更新传入的字段，未识别的 key 会被忽略。"""
    db_url = _get_db_url(db_url)
    if not db_url or not doc_id:
        return False

    sets: list[str] = []
    params: list[Any] = []
    for key, column in _ENRICH_COLUMNS.items():
        if key not in fields:
            continue
        value = fields[key]
        if key in ("affected_parties", "key_provisions", "enrich_meta"):
            value = json.dumps(value if value is not None else ({} if key == "enrich_meta" else []),
                               ensure_ascii=False)
        sets.append(f"{column} = %s")
        params.append(value)

    if full_text is not None:
        sets.append("full_text = %s")
        params.append(full_text)
        sets.append("full_text_fetched_at = NOW()")

    if not sets:
        logging.warning(f"save_policy_enrichment 没有可写字段: doc_id={doc_id}")
        return False

    sets.append("enriched_at = NOW()")
    params.append(doc_id)
    sql = f"UPDATE policy_documents SET {', '.join(sets)} WHERE id = %s"
    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(sql, tuple(params))
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:  # noqa: BLE001
        logging.warning(f"Failed to save policy enrichment for {doc_id}: {e}")
        return False


def count_policy_documents(*, db_url: str | None = None) -> dict[str, int]:
    db_url = _get_db_url(db_url)
    if not db_url:
        return {"total": 0, "enriched": 0, "unenriched": 0}
    sql = """
        SELECT COUNT(*) AS total,
               COUNT(enriched_at) AS enriched,
               COUNT(*) - COUNT(enriched_at) AS unenriched
        FROM policy_documents
    """
    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(sql)
            total, enriched, unenriched = cur.fetchone()
            return {"total": int(total), "enriched": int(enriched), "unenriched": int(unenriched)}
    except Exception as e:  # noqa: BLE001
        logging.warning(f"Failed to count policy documents: {e}")
        return {"total": 0, "enriched": 0, "unenriched": 0}


def get_untriaged_documents(
    *,
    limit: int = 200,
    site_key: str | None = None,
    level: str | None = None,
    min_title_length: int = 8,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    """取尚未预筛的文档。只带标题等轻量字段 —— 预筛不需要正文。"""
    db_url = _get_db_url(db_url)
    if not db_url:
        return []
    clauses = ["triaged_at IS NULL", "CHAR_LENGTH(title) >= %s"]
    params: list[Any] = [max(1, int(min_title_length))]
    if site_key:
        clauses.append("site_key = %s")
        params.append(site_key)
    if level:
        clauses.append("level = %s")
        params.append(level)
    params.append(max(1, int(limit)))
    sql = f"""
        SELECT id, site_key, site_name, level, region, title, published_at
        FROM policy_documents
        WHERE {' AND '.join(clauses)}
        ORDER BY COALESCE(published_at, first_seen_at) DESC NULLS LAST, id
        LIMIT %s
    """
    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(sql, tuple(params))
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:  # noqa: BLE001
        logging.warning(f"Failed to query untriaged policy documents: {e}")
        return []


def save_triage_results(
    results: list[dict[str, Any]],
    *,
    db_url: str | None = None,
) -> int:
    """批量回写预筛结果。每条需含 id / ai_relevance / is_policy。"""
    db_url = _get_db_url(db_url)
    if not db_url or not results:
        return 0
    sql = """
        UPDATE policy_documents
        SET triaged_at = NOW(),
            triage_relevance = %s,
            triage_is_policy = %s
        WHERE id = %s
    """
    saved = 0
    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            for row in results:
                doc_id = str(row.get("id", "")).strip()
                if not doc_id:
                    continue
                relevance = row.get("ai_relevance")
                relevance = int(relevance) if isinstance(relevance, int) and 1 <= relevance <= 5 else None
                is_policy = row.get("is_policy")
                cur.execute(
                    sql,
                    (relevance, bool(is_policy) if is_policy is not None else None, doc_id),
                )
                saved += cur.rowcount
            conn.commit()
    except Exception as e:  # noqa: BLE001
        logging.warning(f"Failed to save policy triage results: {e}")
    return saved


def count_policy_triage(*, db_url: str | None = None) -> dict[str, int]:
    """预筛分布，用于判断阈值设得合不合理。"""
    db_url = _get_db_url(db_url)
    if not db_url:
        return {}
    sql = """
        SELECT COALESCE(triage_relevance::text, 'untriaged') AS bucket,
               COUNT(*) AS n
        FROM policy_documents
        GROUP BY 1 ORDER BY 1
    """
    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(sql)
            return {str(row[0]): int(row[1]) for row in cur.fetchall()}
    except Exception as e:  # noqa: BLE001
        logging.warning(f"Failed to count policy triage: {e}")
        return {}
