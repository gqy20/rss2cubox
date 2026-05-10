"""Global Insights CRUD — save and query global analysis results."""
import json
import logging
from typing import Any

import psycopg

from rss2cubox.db_client._base import _get_db_url

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
    db_url = _get_db_url(db_url)

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
    db_url = _get_db_url(db_url)

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
    db_url = _get_db_url(db_url)

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
