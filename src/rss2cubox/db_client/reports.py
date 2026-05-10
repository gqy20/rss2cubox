"""Daily Reports CRUD — save and query daily reports."""
import json
import logging
from typing import Any

import psycopg

from rss2cubox.db_client._base import _get_db_url

DAILY_REPORTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_reports (
    id           SERIAL PRIMARY KEY,
    report_date  DATE NOT NULL UNIQUE,
    generated_at TIMESTAMPTZ NOT NULL,
    data         JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_daily_reports_date ON daily_reports(report_date DESC);
"""


def save_daily_report(
    payload: dict[str, Any],
    db_url: str | None = None,
) -> bool:
    """Save daily report to local PostgreSQL (idempotent by report_date)."""
    db_url = _get_db_url(db_url)

    if not db_url:
        logging.warning("LOCAL_DB_URL not set, skipping daily_report save")
        return False

    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(DAILY_REPORTS_SCHEMA)
            cur.execute(
                """
                INSERT INTO daily_reports (report_date, generated_at, data)
                VALUES (%s::date, %s::timestamptz, %s)
                ON CONFLICT (report_date) DO UPDATE SET
                    generated_at = EXCLUDED.generated_at,
                    data = EXCLUDED.data
                """,
                (
                    payload.get("report_date"),
                    payload.get("generated_at"),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            conn.commit()
            return True
    except Exception as e:
        logging.warning(f"Failed to save daily_report: {e}")
        return False


def get_daily_report(
    date_str: str,
    db_url: str | None = None,
) -> dict[str, Any] | None:
    """Get a single daily report by date."""
    db_url = _get_db_url(db_url)

    if not db_url:
        logging.warning("LOCAL_DB_URL not set, cannot query daily_reports")
        return None

    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(DAILY_REPORTS_SCHEMA)
            cur.execute(
                "SELECT data FROM daily_reports WHERE report_date = %s::date",
                (date_str,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            data = row[0]
            return json.loads(data) if isinstance(data, str) else data
    except Exception as e:
        logging.warning(f"Failed to get daily_report: {e}")
        return None


def get_recent_reports(
    limit: int = 30,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    """Get recent daily reports ordered by date descending."""
    db_url = _get_db_url(db_url)

    if not db_url:
        logging.warning("LOCAL_DB_URL not set, cannot query daily_reports")
        return []

    try:
        with psycopg.connect(db_url) as conn:
            cur = conn.cursor()
            cur.execute(DAILY_REPORTS_SCHEMA)
            cur.execute(
                "SELECT data FROM daily_reports ORDER BY report_date DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
            result = []
            for (data,) in rows:
                result.append(json.loads(data) if isinstance(data, str) else data)
            return result
    except Exception as e:
        logging.warning(f"Failed to get recent daily_reports: {e}")
        return []
