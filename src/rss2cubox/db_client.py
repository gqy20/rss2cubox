"""Local PostgreSQL database client for storing articles.

This module provides a local PostgreSQL fallback for article storage,
complementing the remote IC API. Useful for local development and debugging.
"""
import json
import logging
import os
from datetime import datetime
from typing import Any

import psycopg

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
    publish_time        TIMESTAMP,
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
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
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
    ADD COLUMN IF NOT EXISTS enrich_meta JSONB DEFAULT '{}';

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

    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()

    if not db_url:
        logging.warning("LOCAL_DB_URL not set, skipping local DB save")
        return 0

    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()

            # Create table if not exists
            cur.execute(ARTICLES_SCHEMA)

            # Insert each article
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
                        created_at, updated_at
                    ) VALUES (
                        %(id)s, %(source_type)s, %(source_feed_id)s, %(source_feed_name)s,
                        %(source_article_id)s, %(title)s, %(url)s, %(pic_url)s, %(description)s,
                        %(publish_time)s, %(tags)s, %(importance_score)s, %(reason)s, %(actionable)s, %(hidden_signal)s,
                        %(content_source)s, %(signal_type)s, %(evidence_type)s, %(evidence_strength)s,
                        %(novelty_score)s, %(impact_horizon)s, %(audience)s, %(market_stage)s, %(confidence)s,
                        %(entities)s, %(cluster_hint)s, %(watch_keywords)s, %(prediction)s, %(disconfirming_evidence)s,
                        %(enrich_meta)s,
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
                    },
                )

            conn.commit()
            return len(articles)
    except Exception as e:
        logging.warning(f"Failed to save articles to local DB: {e}")
        return 0


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
    if db_url is None:
        import os
        db_url = os.getenv("LOCAL_DB_URL", "").strip()

    if not db_url:
        raise ValueError("LOCAL_DB_URL environment variable is not set")

    with psycopg.connect(db_url) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                id, source_type, source_feed_id, source_feed_name,
                source_article_id, title, url, pic_url, description,
                publish_time, tags, importance_score, reason, actionable, hidden_signal,
                content_source, signal_type, evidence_type, evidence_strength,
                novelty_score, impact_horizon, audience, market_stage, confidence,
                entities, cluster_hint, watch_keywords, prediction, disconfirming_evidence,
                enrich_meta,
                created_at, updated_at
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
    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()

    if not db_url:
        raise ValueError("LOCAL_DB_URL environment variable is not set")

    with psycopg.connect(db_url) as conn:
        cur = conn.cursor()
        if cursor:
            cur.execute(
                """
                SELECT
                    id, source_type, source_feed_id, source_feed_name,
                    source_article_id, title, url, pic_url, description,
                    publish_time, tags, importance_score, reason, actionable, hidden_signal,
                    content_source, signal_type, evidence_type, evidence_strength,
                    novelty_score, impact_horizon, audience, market_stage, confidence,
                    entities, cluster_hint, watch_keywords, prediction, disconfirming_evidence,
                    enrich_meta,
                    created_at, updated_at
                FROM articles
                WHERE publish_time IS NOT NULL AND publish_time < %s::timestamp
                ORDER BY publish_time DESC
                LIMIT %s
                """,
                (cursor, limit),
            )
        else:
            cur.execute(
                """
                SELECT
                    id, source_type, source_feed_id, source_feed_name,
                    source_article_id, title, url, pic_url, description,
                    publish_time, tags, importance_score, reason, actionable, hidden_signal,
                    content_source, signal_type, evidence_type, evidence_strength,
                    novelty_score, impact_horizon, audience, market_stage, confidence,
                    entities, cluster_hint, watch_keywords, prediction, disconfirming_evidence,
                    enrich_meta,
                    created_at, updated_at
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
    if db_url is None:
        import os
        db_url = os.getenv("LOCAL_DB_URL", "").strip()

    if not db_url:
        raise ValueError("LOCAL_DB_URL environment variable is not set")

    with psycopg.connect(db_url) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                id, source_type, source_feed_id, source_feed_name,
                source_article_id, title, url, pic_url, description,
                publish_time, tags, importance_score, reason, actionable, hidden_signal,
                content_source, signal_type, evidence_type, evidence_strength,
                novelty_score, impact_horizon, audience, market_stage, confidence,
                entities, cluster_hint, watch_keywords, prediction, disconfirming_evidence,
                enrich_meta,
                created_at, updated_at
            FROM articles
            WHERE publish_time >= %s AND publish_time < %s::date + INTERVAL '1 day'
            ORDER BY publish_time DESC
            LIMIT %s OFFSET %s
            """,
            (start_date, end_date, limit, offset),
        )

        rows = cur.fetchall()
        return [_row_to_article(row) for row in rows]


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


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _bounded_int(value: Any, lower: int, upper: int) -> int | None:
    return value if isinstance(value, int) and lower <= value <= upper else None


def _bounded_int_list(value: Any, lower: int, upper: int, limit: int) -> list[int]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, int) and lower <= item <= upper][:limit]


def _string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:limit]


def _parse_json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _parse_publish_time(value: Any) -> datetime | None:
    """Parse publish_time to datetime object."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # Try common formats
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


# ── Deduplication Queries ────────────────────────────────────────────────────


def get_all_article_ids(db_url: str | None = None) -> set[str]:
    """Get all processed article IDs from local PostgreSQL.

    Used for deduplication before sending to IC API.

    Args:
        db_url: PostgreSQL connection URL. If None, reads from LOCAL_DB_URL env.

    Returns:
        Set of all article IDs (stable_id / eid).
    """
    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()

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
    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()

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


# ── Global Insights ──────────────────────────────────────────────────────────

GLOBAL_INSIGHTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS global_insights (
    id           SERIAL PRIMARY KEY,
    generated_at TIMESTAMPTZ NOT NULL,
    data         JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_global_insights_generated_at ON global_insights(generated_at DESC);
"""


PREDICTION_LOOP_SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_clusters (
    id                      SERIAL PRIMARY KEY,
    label                   TEXT NOT NULL,
    normalized_label        TEXT NOT NULL,
    signal_type             SMALLINT,
    status                  TEXT NOT NULL DEFAULT 'new',
    summary                 TEXT,
    entities                JSONB DEFAULT '[]',
    watch_keywords          JSONB DEFAULT '[]',
    first_seen_at           TIMESTAMPTZ,
    last_seen_at            TIMESTAMPTZ,
    article_count           INTEGER DEFAULT 0,
    source_count            INTEGER DEFAULT 0,
    avg_importance          NUMERIC,
    avg_evidence_strength   NUMERIC,
    avg_novelty             NUMERIC,
    avg_confidence          NUMERIC,
    prediction_score_avg    NUMERIC,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (normalized_label, signal_type)
);

CREATE TABLE IF NOT EXISTS signal_cluster_articles (
    cluster_id              INTEGER NOT NULL REFERENCES signal_clusters(id) ON DELETE CASCADE,
    article_id              VARCHAR(255) NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    relevance_score         NUMERIC,
    linked_at               TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (cluster_id, article_id)
);

CREATE TABLE IF NOT EXISTS trend_predictions (
    id                      SERIAL PRIMARY KEY,
    signal_cluster_id       INTEGER REFERENCES signal_clusters(id) ON DELETE SET NULL,
    prediction_type         SMALLINT NOT NULL,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    target_start_at         TIMESTAMPTZ NOT NULL,
    target_end_at           TIMESTAMPTZ NOT NULL,
    horizon_days            INTEGER NOT NULL DEFAULT 7,
    prediction_title        TEXT NOT NULL,
    prediction_body         TEXT NOT NULL,
    watch_keywords          JSONB DEFAULT '[]',
    expected_evidence       JSONB DEFAULT '{}',
    disconfirming_evidence  TEXT,
    baseline_metrics        JSONB DEFAULT '{}',
    confidence              SMALLINT,
    status                  TEXT NOT NULL DEFAULT 'pending',
    created_from_insight_id INTEGER
);

CREATE TABLE IF NOT EXISTS prediction_reviews (
    id                      SERIAL PRIMARY KEY,
    prediction_id           INTEGER NOT NULL REFERENCES trend_predictions(id) ON DELETE CASCADE,
    reviewed_at             TIMESTAMPTZ DEFAULT NOW(),
    score                   SMALLINT NOT NULL,
    hit_level               TEXT NOT NULL,
    supporting_articles     JSONB DEFAULT '[]',
    contradicting_articles  JSONB DEFAULT '[]',
    actual_observation      TEXT,
    why_score               TEXT,
    improvement_advice      TEXT,
    review_metrics          JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_signal_clusters_type_status ON signal_clusters(signal_type, status);
CREATE INDEX IF NOT EXISTS idx_signal_clusters_updated_at ON signal_clusters(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_trend_predictions_status_end ON trend_predictions(status, target_end_at);
CREATE INDEX IF NOT EXISTS idx_prediction_reviews_prediction_id ON prediction_reviews(prediction_id);
"""


def ensure_prediction_loop_schema(db_url: str | None = None) -> bool:
    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()

    if not db_url:
        logging.warning("LOCAL_DB_URL not set, skipping prediction loop schema")
        return False

    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(ARTICLES_SCHEMA)
            cur.execute(PREDICTION_LOOP_SCHEMA)
            conn.commit()
            return True
    except Exception as e:
        logging.warning(f"Failed to ensure prediction loop schema: {e}")
        return False


def get_recent_enriched_articles(
    *,
    days: int = 30,
    limit: int = 500,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()
    if not db_url:
        return []

    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(ARTICLES_SCHEMA)
            cur.execute(
                f"""
                SELECT {ARTICLE_SELECT_COLUMNS}
                FROM articles
                WHERE publish_time >= NOW() - (%s * INTERVAL '1 day')
                  AND (
                    hidden_signal IS NOT NULL OR cluster_hint IS NOT NULL
                    OR signal_type IS NOT NULL OR entities != '[]'::jsonb
                  )
                ORDER BY publish_time DESC
                LIMIT %s
                """,
                (days, limit),
            )
            return [_row_to_article(row) for row in cur.fetchall()]
    except Exception as e:
        logging.warning(f"Failed to load recent enriched articles: {e}")
        return []


def _cluster_from_row(row: tuple) -> dict[str, Any]:
    (
        cluster_id, label, normalized_label, signal_type, status, summary,
        entities, watch_keywords, first_seen_at, last_seen_at,
        article_count, source_count, avg_importance, avg_evidence_strength,
        avg_novelty, avg_confidence, prediction_score_avg,
    ) = row
    return {
        "id": cluster_id,
        "cluster_key": f"{signal_type or 12}:{normalized_label}",
        "label": label,
        "normalized_label": normalized_label,
        "signal_type": signal_type,
        "status": status,
        "summary": summary,
        "entities": _parse_json_value(entities, []),
        "watch_keywords": _parse_json_value(watch_keywords, []),
        "first_seen_at": first_seen_at.isoformat() if first_seen_at else None,
        "last_seen_at": last_seen_at.isoformat() if last_seen_at else None,
        "article_count": article_count,
        "source_count": source_count,
        "avg_importance": float(avg_importance) if avg_importance is not None else 0,
        "avg_evidence_strength": float(avg_evidence_strength) if avg_evidence_strength is not None else 0,
        "avg_novelty": float(avg_novelty) if avg_novelty is not None else 0,
        "avg_confidence": float(avg_confidence) if avg_confidence is not None else 0,
        "prediction_score_avg": float(prediction_score_avg) if prediction_score_avg is not None else None,
    }


def get_existing_signal_clusters(limit: int = 200, db_url: str | None = None) -> list[dict[str, Any]]:
    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()
    if not db_url:
        return []

    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(PREDICTION_LOOP_SCHEMA)
            cur.execute(
                """
                SELECT
                    id, label, normalized_label, signal_type, status, summary,
                    entities, watch_keywords, first_seen_at, last_seen_at,
                    article_count, source_count, avg_importance, avg_evidence_strength,
                    avg_novelty, avg_confidence, prediction_score_avg
                FROM signal_clusters sc
                WHERE status != 'invalid'
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [_cluster_from_row(row) for row in cur.fetchall()]
    except Exception as e:
        logging.warning(f"Failed to load existing signal clusters: {e}")
        return []


def get_signal_clusters_for_prediction(limit: int = 20, db_url: str | None = None) -> list[dict[str, Any]]:
    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()
    if not db_url:
        return []

    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(PREDICTION_LOOP_SCHEMA)
            cur.execute(
                """
                SELECT
                    id, label, normalized_label, signal_type, status, summary,
                    entities, watch_keywords, first_seen_at, last_seen_at,
                    article_count, source_count, avg_importance, avg_evidence_strength,
                    avg_novelty, avg_confidence, prediction_score_avg
                FROM signal_clusters sc
                WHERE status IN ('new', 'warming', 'bursting', 'mature')
                  AND NOT EXISTS (
                    SELECT 1 FROM trend_predictions tp
                    WHERE tp.signal_cluster_id = sc.id
                      AND tp.status = 'pending'
                  )
                ORDER BY
                    CASE status WHEN 'bursting' THEN 0 WHEN 'warming' THEN 1 WHEN 'new' THEN 2 ELSE 3 END,
                    article_count DESC,
                    updated_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [_cluster_from_row(row) for row in cur.fetchall()]
    except Exception as e:
        logging.warning(f"Failed to load signal clusters for prediction: {e}")
        return []


def get_recent_prediction_reviews(limit: int = 100, db_url: str | None = None) -> list[dict[str, Any]]:
    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()
    if not db_url:
        return []

    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(PREDICTION_LOOP_SCHEMA)
            cur.execute(
                """
                SELECT
                    pr.prediction_id, pr.reviewed_at, pr.score, pr.hit_level,
                    pr.actual_observation, pr.why_score, pr.improvement_advice,
                    pr.review_metrics, tp.prediction_type, tp.prediction_title,
                    tp.prediction_body, sc.normalized_label, sc.signal_type
                FROM prediction_reviews pr
                JOIN trend_predictions tp ON tp.id = pr.prediction_id
                LEFT JOIN signal_clusters sc ON sc.id = tp.signal_cluster_id
                ORDER BY pr.reviewed_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            reviews: list[dict[str, Any]] = []
            for row in cur.fetchall():
                (
                    prediction_id, reviewed_at, score, hit_level,
                    actual_observation, why_score, improvement_advice,
                    review_metrics, prediction_type, prediction_title,
                    prediction_body, normalized_label, signal_type,
                ) = row
                reviews.append({
                    "prediction_id": prediction_id,
                    "reviewed_at": reviewed_at.isoformat() if reviewed_at else None,
                    "score": score,
                    "hit_level": hit_level,
                    "actual_observation": actual_observation,
                    "why_score": why_score,
                    "improvement_advice": improvement_advice,
                    "review_metrics": _parse_json_value(review_metrics, {}),
                    "prediction_type": prediction_type,
                    "prediction_title": prediction_title,
                    "prediction_body": prediction_body,
                    "signal_cluster_key": f"{signal_type or 12}:{normalized_label}" if normalized_label else "",
                })
            return reviews
    except Exception as e:
        logging.warning(f"Failed to load recent prediction reviews: {e}")
        return []


def get_due_trend_predictions(limit: int = 20, db_url: str | None = None) -> list[dict[str, Any]]:
    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()
    if not db_url:
        return []

    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(PREDICTION_LOOP_SCHEMA)
            cur.execute(
                """
                SELECT
                    tp.id, tp.signal_cluster_id, sc.normalized_label, sc.signal_type,
                    tp.prediction_type, tp.created_at, tp.target_start_at, tp.target_end_at,
                    tp.horizon_days, tp.prediction_title, tp.prediction_body, tp.watch_keywords,
                    tp.expected_evidence, tp.disconfirming_evidence, tp.baseline_metrics,
                    tp.confidence, tp.status
                FROM trend_predictions tp
                LEFT JOIN signal_clusters sc ON sc.id = tp.signal_cluster_id
                WHERE tp.status = 'pending'
                  AND tp.target_end_at <= NOW()
                  AND NOT EXISTS (
                    SELECT 1 FROM prediction_reviews pr
                    WHERE pr.prediction_id = tp.id
                  )
                ORDER BY tp.target_end_at ASC
                LIMIT %s
                """,
                (limit,),
            )
            predictions: list[dict[str, Any]] = []
            for row in cur.fetchall():
                (
                    prediction_id, cluster_id, normalized_label, signal_type,
                    prediction_type, created_at, target_start_at, target_end_at,
                    horizon_days, prediction_title, prediction_body, watch_keywords,
                    expected_evidence, disconfirming_evidence, baseline_metrics,
                    confidence, status,
                ) = row
                predictions.append({
                    "id": prediction_id,
                    "signal_cluster_id": cluster_id,
                    "signal_cluster_key": f"{signal_type or 12}:{normalized_label}" if normalized_label else "",
                    "prediction_type": prediction_type,
                    "created_at": created_at.isoformat() if created_at else None,
                    "target_start_at": target_start_at.isoformat() if target_start_at else None,
                    "target_end_at": target_end_at.isoformat() if target_end_at else None,
                    "horizon_days": horizon_days,
                    "prediction_title": prediction_title,
                    "prediction_body": prediction_body,
                    "watch_keywords": _parse_json_value(watch_keywords, []),
                    "expected_evidence": _parse_json_value(expected_evidence, {}),
                    "disconfirming_evidence": disconfirming_evidence,
                    "baseline_metrics": _parse_json_value(baseline_metrics, {}),
                    "confidence": confidence,
                    "status": status,
                })
            return predictions
    except Exception as e:
        logging.warning(f"Failed to load due trend predictions: {e}")
        return []


def get_prediction_window_articles(prediction: dict[str, Any], limit: int = 200, db_url: str | None = None) -> list[dict[str, Any]]:
    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()
    if not db_url or not prediction.get("signal_cluster_id"):
        return []

    try:
        expected = prediction.get("expected_evidence") if isinstance(prediction.get("expected_evidence"), dict) else {}
        keywords = _string_list(prediction.get("watch_keywords"), 20)
        keywords.extend(_string_list(expected.get("required_keywords"), 20))
        keyword_terms = []
        seen_terms: set[str] = set()
        for keyword in keywords:
            term = keyword.strip()
            if term and term.lower() not in seen_terms:
                seen_terms.add(term.lower())
                keyword_terms.append(f"%{term}%")

        keyword_clause = ""
        params: list[Any] = [prediction.get("signal_cluster_id")]
        if keyword_terms:
            checks: list[str] = []
            for term in keyword_terms:
                checks.append(
                    "(a.title ILIKE %s OR a.description ILIKE %s OR a.hidden_signal ILIKE %s "
                    "OR a.reason ILIKE %s OR a.cluster_hint ILIKE %s)"
                )
                params.extend([term, term, term, term, term])
            keyword_clause = " OR " + " OR ".join(checks)
        params.extend([
            prediction.get("target_start_at"),
            prediction.get("target_end_at"),
            limit,
        ])

        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(ARTICLES_SCHEMA)
            cur.execute(PREDICTION_LOOP_SCHEMA)
            cur.execute(
                f"""
                SELECT {ARTICLE_SELECT_COLUMNS}
                FROM articles a
                LEFT JOIN signal_cluster_articles sca
                    ON sca.article_id = a.id
                    AND sca.cluster_id = %s
                WHERE (
                    sca.cluster_id IS NOT NULL
                    {keyword_clause}
                )
                  AND a.publish_time >= %s::timestamptz
                  AND a.publish_time <= %s::timestamptz
                ORDER BY a.publish_time DESC
                LIMIT %s
                """,
                params,
            )
            return [_row_to_article(row) for row in cur.fetchall()]
    except Exception as e:
        logging.warning(f"Failed to load prediction window articles: {e}")
        return []


def save_signal_clusters(cluster_result: dict[str, list[dict[str, Any]]], db_url: str | None = None) -> dict[str, int]:
    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()
    if not db_url:
        logging.warning("LOCAL_DB_URL not set, skipping signal_clusters save")
        return {}

    cluster_ids: dict[str, int] = {}
    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(ARTICLES_SCHEMA)
            cur.execute(PREDICTION_LOOP_SCHEMA)
            for cluster in cluster_result.get("clusters", []):
                cluster_key = str(cluster.get("cluster_key") or "").strip()
                normalized_label = str(cluster.get("normalized_label") or cluster_key.split(":", 1)[-1]).strip()
                cur.execute(
                    """
                    INSERT INTO signal_clusters (
                        label, normalized_label, signal_type, status, summary,
                        entities, watch_keywords, first_seen_at, last_seen_at,
                        article_count, source_count, avg_importance, avg_evidence_strength,
                        avg_novelty, avg_confidence, updated_at
                    ) VALUES (
                        %(label)s, %(normalized_label)s, %(signal_type)s, %(status)s, %(summary)s,
                        %(entities)s, %(watch_keywords)s, %(first_seen_at)s::timestamptz, %(last_seen_at)s::timestamptz,
                        %(article_count)s, %(source_count)s, %(avg_importance)s, %(avg_evidence_strength)s,
                        %(avg_novelty)s, %(avg_confidence)s, NOW()
                    )
                    ON CONFLICT (normalized_label, signal_type) DO UPDATE SET
                        label = EXCLUDED.label,
                        status = EXCLUDED.status,
                        summary = EXCLUDED.summary,
                        entities = EXCLUDED.entities,
                        watch_keywords = EXCLUDED.watch_keywords,
                        first_seen_at = LEAST(signal_clusters.first_seen_at, EXCLUDED.first_seen_at),
                        last_seen_at = GREATEST(signal_clusters.last_seen_at, EXCLUDED.last_seen_at),
                        article_count = EXCLUDED.article_count,
                        source_count = EXCLUDED.source_count,
                        avg_importance = EXCLUDED.avg_importance,
                        avg_evidence_strength = EXCLUDED.avg_evidence_strength,
                        avg_novelty = EXCLUDED.avg_novelty,
                        avg_confidence = EXCLUDED.avg_confidence,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    {
                        "label": cluster.get("label") or normalized_label,
                        "normalized_label": normalized_label,
                        "signal_type": _bounded_int(cluster.get("signal_type"), 1, 12),
                        "status": cluster.get("status") or "new",
                        "summary": cluster.get("summary") or "",
                        "entities": json.dumps(_string_list(cluster.get("entities"), 20), ensure_ascii=False),
                        "watch_keywords": json.dumps(_string_list(cluster.get("watch_keywords"), 20), ensure_ascii=False),
                        "first_seen_at": cluster.get("first_seen_at"),
                        "last_seen_at": cluster.get("last_seen_at"),
                        "article_count": int(cluster.get("article_count") or 0),
                        "source_count": int(cluster.get("source_count") or 0),
                        "avg_importance": cluster.get("avg_importance"),
                        "avg_evidence_strength": cluster.get("avg_evidence_strength"),
                        "avg_novelty": cluster.get("avg_novelty"),
                        "avg_confidence": cluster.get("avg_confidence"),
                    },
                )
                row = cur.fetchone()
                if row and cluster_key:
                    cluster_ids[cluster_key] = int(row[0])

            for link in cluster_result.get("links", []):
                cluster_id = cluster_ids.get(str(link.get("cluster_key") or ""))
                article_id = str(link.get("article_id") or "").strip()
                if not cluster_id or not article_id:
                    continue
                cur.execute(
                    """
                    INSERT INTO signal_cluster_articles (cluster_id, article_id, relevance_score)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (cluster_id, article_id) DO UPDATE SET
                        relevance_score = EXCLUDED.relevance_score,
                        linked_at = NOW()
                    """,
                    (cluster_id, article_id, link.get("relevance_score", 1.0)),
                )
            conn.commit()
            return cluster_ids
    except Exception as e:
        logging.warning(f"Failed to save signal clusters: {e}")
        return {}


def save_trend_predictions(
    predictions: list[dict[str, Any]],
    cluster_ids_by_key: dict[str, int],
    db_url: str | None = None,
) -> int:
    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()
    if not db_url or not predictions:
        return 0

    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(PREDICTION_LOOP_SCHEMA)
            inserted = 0
            for prediction in predictions:
                cluster_id = cluster_ids_by_key.get(str(prediction.get("signal_cluster_key") or ""))
                cur.execute(
                    """
                    INSERT INTO trend_predictions (
                        signal_cluster_id, prediction_type, target_start_at, target_end_at,
                        horizon_days, prediction_title, prediction_body, watch_keywords,
                        expected_evidence, disconfirming_evidence, baseline_metrics,
                        confidence, status
                    )
                    SELECT
                        %(signal_cluster_id)s, %(prediction_type)s, %(target_start_at)s::timestamptz, %(target_end_at)s::timestamptz,
                        %(horizon_days)s, %(prediction_title)s, %(prediction_body)s, %(watch_keywords)s,
                        %(expected_evidence)s, %(disconfirming_evidence)s, %(baseline_metrics)s,
                        %(confidence)s, %(status)s
                    WHERE NOT EXISTS (
                        SELECT 1 FROM trend_predictions existing
                        WHERE existing.signal_cluster_id IS NOT DISTINCT FROM %(signal_cluster_id)s
                          AND existing.prediction_type = %(prediction_type)s
                          AND LOWER(existing.prediction_title) = LOWER(%(prediction_title)s)
                          AND existing.created_at >= NOW() - INTERVAL '30 days'
                    )
                    RETURNING id
                    """,
                    {
                        "signal_cluster_id": cluster_id,
                        "prediction_type": prediction.get("prediction_type"),
                        "target_start_at": prediction.get("target_start_at"),
                        "target_end_at": prediction.get("target_end_at"),
                        "horizon_days": prediction.get("horizon_days", 7),
                        "prediction_title": prediction.get("prediction_title", ""),
                        "prediction_body": prediction.get("prediction_body", ""),
                        "watch_keywords": json.dumps(_string_list(prediction.get("watch_keywords"), 20), ensure_ascii=False),
                        "expected_evidence": json.dumps(prediction.get("expected_evidence") if isinstance(prediction.get("expected_evidence"), dict) else {}, ensure_ascii=False),
                        "disconfirming_evidence": prediction.get("disconfirming_evidence"),
                        "baseline_metrics": json.dumps(prediction.get("baseline_metrics") if isinstance(prediction.get("baseline_metrics"), dict) else {}, ensure_ascii=False),
                        "confidence": _bounded_int(prediction.get("confidence"), 1, 5),
                        "status": prediction.get("status", "pending"),
                    },
                )
                if cur.fetchone():
                    inserted += 1
            conn.commit()
            return inserted
    except Exception as e:
        logging.warning(f"Failed to save trend predictions: {e}")
        return 0


def save_prediction_review(review: dict[str, Any], db_url: str | None = None) -> bool:
    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()
    if not db_url:
        return False

    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(PREDICTION_LOOP_SCHEMA)
            cur.execute(
                """
                INSERT INTO prediction_reviews (
                    prediction_id, score, hit_level, supporting_articles, contradicting_articles,
                    actual_observation, why_score, improvement_advice, review_metrics
                ) VALUES (
                    %(prediction_id)s, %(score)s, %(hit_level)s, %(supporting_articles)s, %(contradicting_articles)s,
                    %(actual_observation)s, %(why_score)s, %(improvement_advice)s, %(review_metrics)s
                )
                """,
                {
                    "prediction_id": review.get("prediction_id"),
                    "score": _bounded_int(review.get("score"), 1, 5),
                    "hit_level": review.get("hit_level", ""),
                    "supporting_articles": json.dumps(_string_list(review.get("supporting_articles"), 100), ensure_ascii=False),
                    "contradicting_articles": json.dumps(_string_list(review.get("contradicting_articles"), 100), ensure_ascii=False),
                    "actual_observation": review.get("actual_observation"),
                    "why_score": review.get("why_score"),
                    "improvement_advice": review.get("improvement_advice"),
                    "review_metrics": json.dumps(review.get("review_metrics") if isinstance(review.get("review_metrics"), dict) else {}, ensure_ascii=False),
                },
            )
            cur.execute(
                """
                UPDATE trend_predictions
                SET status = 'reviewed'
                WHERE id = %s
                """,
                (review.get("prediction_id"),),
            )
            cur.execute(
                """
                UPDATE signal_clusters sc
                SET prediction_score_avg = sub.avg_score
                FROM (
                    SELECT tp.signal_cluster_id, AVG(pr.score)::numeric AS avg_score
                    FROM trend_predictions tp
                    JOIN prediction_reviews pr ON pr.prediction_id = tp.id
                    WHERE tp.signal_cluster_id IS NOT NULL
                    GROUP BY tp.signal_cluster_id
                ) sub
                WHERE sc.id = sub.signal_cluster_id
                """,
            )
            conn.commit()
            return True
    except Exception as e:
        logging.warning(f"Failed to save prediction review: {e}")
        return False


def save_global_insights(
    payload: dict[str, Any],
    db_url: str | None = None,
) -> bool:
    """Save global insights to local PostgreSQL database.

    Args:
        payload: Global insights data from global_agent.
        db_url: PostgreSQL connection URL. If None, reads from LOCAL_DB_URL env.

    Returns:
        True if saved successfully, False otherwise.
    """
    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()

    if not db_url:
        logging.warning("LOCAL_DB_URL not set, skipping global_insights save")
        return False

    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(GLOBAL_INSIGHTS_SCHEMA)
            cur.execute(
                """
                INSERT INTO global_insights (generated_at, data)
                VALUES (%s::timestamptz, %s)
                """,
                (
                    payload.get("generated_at"),
                    payload,
                ),
            )
            conn.commit()
            return True
    except Exception as e:
        logging.warning(f"Failed to save global_insights to local DB: {e}")
        return False


def get_latest_global_insights(
    db_url: str | None = None,
) -> dict[str, Any] | None:
    """Get the latest global insights from local PostgreSQL.

    Args:
        db_url: PostgreSQL connection URL. If None, reads from LOCAL_DB_URL env.

    Returns:
        Latest global insights dict, or None if not found.
    """
    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()

    if not db_url:
        logging.warning("LOCAL_DB_URL not set, cannot query global_insights")
        return None

    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT generated_at, data
                FROM global_insights
                ORDER BY generated_at DESC
                LIMIT 1
                """,
            )
            row = cur.fetchone()
            if row is None:
                return None
            _, data = row
            if isinstance(data, str):
                return json.loads(data)
            return data
    except Exception as e:
        logging.warning(f"Failed to get latest global_insights from local DB: {e}")
        return None


def get_all_global_insights(
    db_url: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Get all global insights from local PostgreSQL.

    Args:
        db_url: PostgreSQL connection URL. If None, reads from LOCAL_DB_URL env.
        limit: Maximum number of insights to return.

    Returns:
        List of global insights dicts ordered by generated_at descending.
    """
    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()

    if not db_url:
        logging.warning("LOCAL_DB_URL not set, cannot query global_insights")
        return []

    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT generated_at, data
                FROM global_insights
                ORDER BY generated_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            result = []
            for _, data in rows:
                if isinstance(data, str):
                    result.append(json.loads(data))
                else:
                    result.append(data)
            return result
    except Exception as e:
        logging.warning(f"Failed to get global_insights from local DB: {e}")
        return []
