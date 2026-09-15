"""政策文件的本地存储与信源健康度记录。

两张表都独立于现有 articles / global_insights，删掉政策模块不会留下残留。

policy_source_state 是失效监测的核心：爬虫最危险的不是抓不到，而是**静默失效**
（选择器过时 → 返回 0 条 → 不报错 → 你以为最近没有新政策）。所以这里记录每个
站点的连续空跑次数，由 get_stale_sources() 供告警和 make doctor 消费。
"""
from __future__ import annotations

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
               obligation_level, ai_relevance, summary, source_quote, enriched_at
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
