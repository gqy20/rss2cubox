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
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_articles_publish_time ON articles(publish_time DESC);
CREATE INDEX IF NOT EXISTS idx_articles_source_type ON articles(source_type);
CREATE INDEX IF NOT EXISTS idx_articles_importance_score ON articles(importance_score);
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
                        created_at, updated_at
                    ) VALUES (
                        %(id)s, %(source_type)s, %(source_feed_id)s, %(source_feed_name)s,
                        %(source_article_id)s, %(title)s, %(url)s, %(pic_url)s, %(description)s,
                        %(publish_time)s, %(tags)s, %(importance_score)s, %(reason)s, %(actionable)s, %(hidden_signal)s,
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
                created_at, updated_at
            FROM articles
            ORDER BY publish_time DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
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


def _row_to_article(row: tuple) -> dict[str, Any]:
    """Convert a database row to an article dictionary."""
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
        created_at,
        updated_at,
    ) = row

    return {
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


# ── Global Insights ──────────────────────────────────────────────────────────

GLOBAL_INSIGHTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS global_insights (
    id           SERIAL PRIMARY KEY,
    generated_at TIMESTAMPTZ NOT NULL,
    data         JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_global_insights_generated_at ON global_insights(generated_at DESC);
"""


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
                    json.dumps(payload, ensure_ascii=False),
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
