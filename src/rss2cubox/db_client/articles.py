"""Articles CRUD — save, query, fulltext, dedup helpers."""
import json
import logging
import os
from typing import Any

import psycopg

from rss2cubox.db_client._base import (
    _bounded_int,
    _bounded_int_list,
    _get_db_url,
    _optional_text,
    _parse_json_value,
    _parse_publish_time,
    _string_list,
)

ARTICLES_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id                  VARCHAR(255) PRIMARY KEY,
    source_type         VARCHAR(50) NOT NULL,
    source_feed_id      VARCHAR(500),
    source_feed_name    VARCHAR(500),
    source_article_id   VARCHAR(500),
    title               TEXT NOT NULL,
    url                 TEXT,
    pic_url             TEXT,
    description         TEXT,
    publish_time        TIMESTAMPTZ,
    tags                JSONB DEFAULT '[]',
    importance_score    INTEGER DEFAULT 3,
    reason              TEXT,
    actionable          TEXT,
    hidden_signal       TEXT,
    content_source      TEXT,
    signal_type         SMALLINT,
    evidence_type       SMALLINT,
    evidence_strength   SMALLINT,
    novelty_score       SMALLINT,
    impact_horizon      SMALLINT,
    audience            JSONB DEFAULT '[]',
    market_stage        SMALLINT,
    confidence          SMALLINT,
    entities            JSONB DEFAULT '[]',
    cluster_hint        TEXT,
    watch_keywords      JSONB DEFAULT '[]',
    prediction          TEXT,
    disconfirming_evidence TEXT,
    enrich_meta         JSONB DEFAULT '{}',
    full_text           TEXT,
    full_text_source     TEXT,
    full_text_fetched_at TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS content_source TEXT,
    ADD COLUMN IF NOT EXISTS signal_type SMALLINT,
    ADD COLUMN IF NOT EXISTS evidence_type SMALLINT,
    ADD COLUMN IF NOT EXISTS evidence_strength SMALLINT,
    ADD COLUMN IF NOT EXISTS novelty_score SMALLINT,
    ADD COLUMN IF NOT EXISTS impact_horizon SMALLINT,
    ADD COLUMN IF NOT EXISTS audience JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS market_stage SMALLINT,
    ADD COLUMN IF NOT EXISTS confidence SMALLINT,
    ADD COLUMN IF NOT EXISTS entities JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS cluster_hint TEXT,
    ADD COLUMN IF NOT EXISTS watch_keywords JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS prediction TEXT,
    ADD COLUMN IF NOT EXISTS disconfirming_evidence TEXT,
    ADD COLUMN IF NOT EXISTS enrich_meta JSONB DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS full_text TEXT,
    ADD COLUMN IF NOT EXISTS full_text_source TEXT,
    ADD COLUMN IF NOT EXISTS full_text_fetched_at TIMESTAMPTZ;

-- Optimized index for cursor-based pagination (covering index)
CREATE INDEX IF NOT EXISTS idx_articles_pub_time_cover ON articles(publish_time DESC);
-- Index for source_type filtering
CREATE INDEX IF NOT EXISTS idx_articles_source_type ON articles(source_type);
-- Index for importance_score filtering
CREATE INDEX IF NOT EXISTS idx_articles_importance_score ON articles(importance_score);
-- GIN index for JSONB tags search
CREATE INDEX IF NOT EXISTS idx_articles_tags ON articles USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_articles_signal_type ON articles(signal_type);
CREATE INDEX IF NOT EXISTS idx_articles_evidence_type ON articles(evidence_type);
CREATE INDEX IF NOT EXISTS idx_articles_evidence_strength ON articles(evidence_strength);
CREATE INDEX IF NOT EXISTS idx_articles_novelty_score ON articles(novelty_score);
CREATE INDEX IF NOT EXISTS idx_articles_cluster_hint ON articles(cluster_hint);
CREATE INDEX IF NOT EXISTS idx_articles_entities ON articles USING GIN (entities);
CREATE INDEX IF NOT EXISTS idx_articles_watch_keywords ON articles USING GIN (watch_keywords);
CREATE INDEX IF NOT EXISTS idx_articles_full_text_source ON articles(full_text_source);
"""


def save_articles(
    articles: list[dict[str, Any]],
    db_url: str | None = None,
) -> int:
    """Save articles to local PostgreSQL database.

    Args:
        articles: List of article records to save.
        db_url: PostgreSQL connection URL. If None, reads from LOCAL_DB_URL env.

    Returns:
        Number of articles saved, or 0 if error occurs.
    """
    if not articles:
        return 0

    db_url = _get_db_url(db_url)

    if not db_url:
        logging.warning("LOCAL_DB_URL not set, skipping local DB save")
        return 0

    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()

            cur.execute(ARTICLES_SCHEMA)

            for article in articles:
                importance = article.get("importance_score")
                if not isinstance(importance, int) or not (1 <= importance <= 5):
                    importance = 3
                cur.execute(
                    """
                    INSERT INTO articles (
                        id, source_type, source_feed_id, source_feed_name,
                        source_article_id, title, url, pic_url, description,
                        publish_time, tags, importance_score, reason, actionable, hidden_signal,
                        content_source, signal_type, evidence_type, evidence_strength,
                        novelty_score, impact_horizon, audience, market_stage, confidence,
                        entities, cluster_hint, watch_keywords, prediction, disconfirming_evidence,
                        enrich_meta,
                        full_text, full_text_source, full_text_fetched_at,
                        created_at, updated_at
                    ) VALUES (
                        %(id)s, %(source_type)s, %(source_feed_id)s, %(source_feed_name)s,
                        %(source_article_id)s, %(title)s, %(url)s, %(pic_url)s, %(description)s,
                        %(publish_time)s, %(tags)s, %(importance_score)s, %(reason)s, %(actionable)s, %(hidden_signal)s,
                        %(content_source)s, %(signal_type)s, %(evidence_type)s, %(evidence_strength)s,
                        %(novelty_score)s, %(impact_horizon)s, %(audience)s, %(market_stage)s, %(confidence)s,
                        %(entities)s, %(cluster_hint)s, %(watch_keywords)s, %(prediction)s, %(disconfirming_evidence)s,
                        %(enrich_meta)s,
                        %(full_text)s, %(full_text_source)s, %(full_text_fetched_at)s,
                        NOW(), NOW()
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        url = EXCLUDED.url,
                        pic_url = EXCLUDED.pic_url,
                        description = EXCLUDED.description,
                        tags = EXCLUDED.tags,
                        importance_score = EXCLUDED.importance_score,
                        reason = EXCLUDED.reason,
                        actionable = EXCLUDED.actionable,
                        hidden_signal = EXCLUDED.hidden_signal,
                        content_source = EXCLUDED.content_source,
                        signal_type = EXCLUDED.signal_type,
                        evidence_type = EXCLUDED.evidence_type,
                        evidence_strength = EXCLUDED.evidence_strength,
                        novelty_score = EXCLUDED.novelty_score,
                        impact_horizon = EXCLUDED.impact_horizon,
                        audience = EXCLUDED.audience,
                        market_stage = EXCLUDED.market_stage,
                        confidence = EXCLUDED.confidence,
                        entities = EXCLUDED.entities,
                        cluster_hint = EXCLUDED.cluster_hint,
                        watch_keywords = EXCLUDED.watch_keywords,
                        prediction = EXCLUDED.prediction,
                        disconfirming_evidence = EXCLUDED.disconfirming_evidence,
                        enrich_meta = EXCLUDED.enrich_meta,
                        full_text = COALESCE(EXCLUDED.full_text, articles.full_text),
                        full_text_source = COALESCE(EXCLUDED.full_text_source, articles.full_text_source),
                        full_text_fetched_at = COALESCE(EXCLUDED.full_text_fetched_at, articles.full_text_fetched_at),
                        updated_at = NOW()
                    """,
                    {
                        "id": article.get("id", ""),
                        "source_type": article.get("source_type", "unknown"),
                        "source_feed_id": article.get("source_feed_id", ""),
                        "source_feed_name": article.get("source_feed_name", ""),
                        "source_article_id": article.get("source_article_id", ""),
                        "title": article.get("title", ""),
                        "url": article.get("url", ""),
                        "pic_url": article.get("pic_url", ""),
                        "description": article.get("description", ""),
                        "publish_time": _parse_publish_time(article.get("publish_time")),
                        "tags": json.dumps(article.get("tags", []), ensure_ascii=False),
                        "importance_score": importance,
                        "reason": article.get("reason", ""),
                        "actionable": article.get("actionable", ""),
                        "hidden_signal": article.get("hidden_signal", ""),
                        "content_source": _optional_text(article.get("content_source")),
                        "signal_type": _bounded_int(article.get("signal_type"), 1, 12),
                        "evidence_type": _bounded_int(article.get("evidence_type"), 1, 12),
                        "evidence_strength": _bounded_int(article.get("evidence_strength"), 1, 5),
                        "novelty_score": _bounded_int(article.get("novelty_score"), 1, 5),
                        "impact_horizon": _bounded_int(article.get("impact_horizon"), 1, 5),
                        "audience": json.dumps(_bounded_int_list(article.get("audience"), 1, 8, 3), ensure_ascii=False),
                        "market_stage": _bounded_int(article.get("market_stage"), 1, 6),
                        "confidence": _bounded_int(article.get("confidence"), 1, 5),
                        "entities": json.dumps(_string_list(article.get("entities"), 8), ensure_ascii=False),
                        "cluster_hint": _optional_text(article.get("cluster_hint")),
                        "watch_keywords": json.dumps(_string_list(article.get("watch_keywords"), 8), ensure_ascii=False),
                        "prediction": _optional_text(article.get("prediction")),
                        "disconfirming_evidence": _optional_text(article.get("disconfirming_evidence")),
                        "enrich_meta": json.dumps(article.get("enrich_meta") if isinstance(article.get("enrich_meta"), dict) else {}, ensure_ascii=False),
                        "full_text": _optional_text(article.get("full_text")),
                        "full_text_source": _optional_text(article.get("full_text_source")),
                        "full_text_fetched_at": article.get("full_text_fetched_at"),
                    },
                )

            conn.commit()
            return len(articles)
    except Exception as e:
        logging.warning(f"Failed to save articles to local DB: {e}")
        return 0


def save_fulltext(
    db_url: str | None = None,
    *,
    eid: str,
    full_text: str,
    source: str,
) -> bool:
    """单条更新文章全文（幂等：重复写入不报错）。"""
    db_url = _get_db_url(db_url)
    if not db_url or not eid or not full_text:
        return False
    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(ARTICLES_SCHEMA)
            cur.execute(
                """
                UPDATE articles SET
                    full_text = %s,
                    full_text_source = %s,
                    full_text_fetched_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (full_text, source, eid),
            )
            conn.commit()
            return True
    except Exception as e:
        logging.warning(f"Failed to save fulltext for {eid}: {e}")
        return False


def save_fulltext_batch(
    results: dict[str, Any],
    db_url: str | None = None,
) -> int:
    """批量更新全文（results 为 dict[eid, FetchResult]）。"""
    if not results:
        return 0
    db_url = _get_db_url(db_url)
    if not db_url:
        return 0
    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(ARTICLES_SCHEMA)
            updated = 0
            for eid, result in results.items():
                text = getattr(result, "text", None) or ""
                source = getattr(result, "source", "") or ""
                if text and eid:
                    cur.execute(
                        """
                        UPDATE articles SET
                            full_text = %s,
                            full_text_source = %s,
                            full_text_fetched_at = NOW(),
                            updated_at = NOW()
                        WHERE id = %s
                        """,
                        (text, source, eid),
                    )
                    updated += 1
            conn.commit()
            return updated
    except Exception as e:
        logging.warning(f"Failed to save fulltext batch: {e}")
        return 0


def get_fulltexts_by_eids(
    eids: list[str],
    db_url: str | None = None,
) -> dict[str, str]:
    """按 eid 列表批量读取已存全文。返回 {eid: full_text}，无全文的 eid 不在结果中。"""
    if not eids:
        return {}
    db_url = _get_db_url(db_url)
    if not db_url:
        return {}
    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, full_text FROM articles WHERE id = ANY(%s) AND full_text IS NOT NULL AND full_text != ''",
                (eids,),
            )
            return {str(row[0]): str(row[1]) for row in cur.fetchall()}
    except Exception as e:
        logging.warning(f"Failed to get fulltexts by eids: {e}")
        return {}


ARTICLE_SELECT_COLUMNS = """
    id, source_type, source_feed_id, source_feed_name,
    source_article_id, title, url, pic_url, description,
    publish_time, tags, importance_score, reason, actionable, hidden_signal,
    content_source, signal_type, evidence_type, evidence_strength,
    novelty_score, impact_horizon, audience, market_stage, confidence,
    entities, cluster_hint, watch_keywords, prediction, disconfirming_evidence,
    enrich_meta,
    created_at, updated_at
"""


def _row_to_article(row: tuple) -> dict[str, Any]:
    """Convert a database row to an article dictionary."""
    extension_defaults = (
        None,  # content_source
        None,  # signal_type
        None,  # evidence_type
        None,  # evidence_strength
        None,  # novelty_score
        None,  # impact_horizon
        [],  # audience
        None,  # market_stage
        None,  # confidence
        [],  # entities
        None,  # cluster_hint
        [],  # watch_keywords
        None,  # prediction
        None,  # disconfirming_evidence
        {},  # enrich_meta
    )
    if len(row) == 17:
        row = row[:15] + extension_defaults + row[15:]

    (
        id,
        source_type,
        source_feed_id,
        source_feed_name,
        source_article_id,
        title,
        url,
        pic_url,
        description,
        publish_time,
        tags,
        importance_score,
        reason,
        actionable,
        hidden_signal,
        content_source,
        signal_type,
        evidence_type,
        evidence_strength,
        novelty_score,
        impact_horizon,
        audience,
        market_stage,
        confidence,
        entities,
        cluster_hint,
        watch_keywords,
        prediction,
        disconfirming_evidence,
        enrich_meta,
        created_at,
        updated_at,
    ) = row

    article = {
        "id": id,
        "source_type": source_type,
        "source_feed_id": source_feed_id,
        "source_feed_name": source_feed_name,
        "source_article_id": source_article_id,
        "title": title,
        "url": url,
        "pic_url": pic_url,
        "description": description,
        "publish_time": publish_time.isoformat() if publish_time else None,
        "tags": json.loads(tags) if isinstance(tags, str) else tags,
        "importance_score": importance_score if isinstance(importance_score, int) else 3,
        "reason": reason,
        "actionable": actionable,
        "hidden_signal": hidden_signal,
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }
    for key, value in {
        "content_source": content_source,
        "signal_type": signal_type,
        "evidence_type": evidence_type,
        "evidence_strength": evidence_strength,
        "novelty_score": novelty_score,
        "impact_horizon": impact_horizon,
        "audience": _parse_json_value(audience, []),
        "market_stage": market_stage,
        "confidence": confidence,
        "entities": _parse_json_value(entities, []),
        "cluster_hint": cluster_hint,
        "watch_keywords": _parse_json_value(watch_keywords, []),
        "prediction": prediction,
        "disconfirming_evidence": disconfirming_evidence,
        "enrich_meta": _parse_json_value(enrich_meta, {}),
    }.items():
        if value not in (None, "", [], {}):
            article[key] = value
    return article


def get_articles(
    limit: int = 100,
    offset: int = 0,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    """Get articles from local PostgreSQL database.

    Args:
        limit: Maximum number of articles to return.
        offset: Number of articles to skip.
        db_url: PostgreSQL connection URL. If None, reads from LOCAL_DB_URL env.

    Returns:
        List of article dictionaries.
    """
    db_url = _get_db_url(db_url)

    if not db_url:
        raise ValueError("LOCAL_DB_URL environment variable is not set")

    with psycopg.connect(db_url) as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT {ARTICLE_SELECT_COLUMNS}
            FROM articles
            ORDER BY publish_time DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )

        rows = cur.fetchall()
        return [_row_to_article(row) for row in rows]


def get_articles_cursor(
    cursor: str | None = None,
    limit: int = 100,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    """Get articles using cursor-based pagination for efficient deep paging.

    Args:
        cursor: ISO format timestamp string. Returns articles published before this time.
                Use the last item's publish_time from previous page as cursor.
        limit: Maximum number of articles to return.
        db_url: PostgreSQL connection URL. If None, reads from LOCAL_DB_URL env.

    Returns:
        List of article dictionaries, ordered by publish_time DESC.
    """
    db_url = _get_db_url(db_url)

    if not db_url:
        raise ValueError("LOCAL_DB_URL environment variable is not set")

    with psycopg.connect(db_url) as conn:
        cur = conn.cursor()
        if cursor:
            cur.execute(
                f"""
                SELECT {ARTICLE_SELECT_COLUMNS}
                FROM articles
                WHERE publish_time IS NOT NULL AND publish_time < %s::timestamp
                ORDER BY publish_time DESC
                LIMIT %s
                """,
                (cursor, limit),
            )
        else:
            cur.execute(
                f"""
                SELECT {ARTICLE_SELECT_COLUMNS}
                FROM articles
                WHERE publish_time IS NOT NULL
                ORDER BY publish_time DESC
                LIMIT %s
                """,
                (limit,),
            )

        rows = cur.fetchall()
        return [_row_to_article(row) for row in rows]


def get_articles_by_date(
    start_date: str,
    end_date: str,
    limit: int = 100,
    offset: int = 0,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    """Get articles within a date range.

    Args:
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.
        limit: Maximum number of articles to return.
        offset: Number of articles to skip.
        db_url: PostgreSQL connection URL. If None, reads from LOCAL_DB_URL env.

    Returns:
        List of article dictionaries within the date range.
    """
    db_url = _get_db_url(db_url)

    if not db_url:
        raise ValueError("LOCAL_DB_URL environment variable is not set")

    with psycopg.connect(db_url) as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT {ARTICLE_SELECT_COLUMNS}
            FROM articles
            WHERE publish_time >= %s AND publish_time < %s::date + INTERVAL '1 day'
            ORDER BY publish_time DESC
            LIMIT %s OFFSET %s
            """,
            (start_date, end_date, limit, offset),
        )

        rows = cur.fetchall()
        return [_row_to_article(row) for row in rows]


def get_all_article_ids(db_url: str | None = None) -> set[str]:
    """Get all processed article IDs from local PostgreSQL.

    Used for deduplication before sending to IC API.

    Args:
        db_url: PostgreSQL connection URL. If None, reads from LOCAL_DB_URL env.

    Returns:
        Set of all article IDs (stable_id / eid).
    """
    db_url = _get_db_url(db_url)

    if not db_url:
        logging.warning("LOCAL_DB_URL not set, returning empty article IDs set")
        return set()

    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM articles WHERE id IS NOT NULL AND id != ''")
            rows = cur.fetchall()
            return {str(row[0]) for row in rows}
    except Exception as e:
        logging.warning(f"Failed to get article IDs from local DB: {e}")
        return set()


def get_feed_cursors(db_url: str | None = None) -> dict[str, str]:
    """Get the latest publish_time for each source_feed_id.

    Used for feed_cursor-based incremental fetching, matching the IC API behavior.

    Args:
        db_url: PostgreSQL connection URL. If None, reads from LOCAL_DB_URL env.

    Returns:
        dict mapping source_feed_id to latest publish_time ISO string.
    """
    db_url = _get_db_url(db_url)

    if not db_url:
        logging.warning("LOCAL_DB_URL not set, returning empty feed cursors")
        return {}

    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT source_feed_id, MAX(publish_time) AS latest_time
                FROM articles
                WHERE source_feed_id IS NOT NULL
                  AND source_feed_id != ''
                  AND publish_time IS NOT NULL
                GROUP BY source_feed_id
                """
            )
            rows = cur.fetchall()
            return {
                str(row[0]): row[1].isoformat() if row[1] else ""
                for row in rows
            }
    except Exception as e:
        logging.warning(f"Failed to get feed cursors from local DB: {e}")
        return {}
