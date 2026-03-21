"""
Legacy Neon compatibility helpers.

These tables are no longer part of the main sync path. They are kept only for
historical scripts and one-off migration/debug workflows.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg

STATE_DDL = """
CREATE TABLE IF NOT EXISTS processed_items (
    id   TEXT PRIMARY KEY,
    data JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS feed_cursors (
    feed_key  TEXT PRIMARY KEY,
    cursor_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feed_failures (
    feed_key  TEXT PRIMARY KEY,
    data      JSONB NOT NULL
);
"""

RUN_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS run_events (
    event_key  TEXT PRIMARY KEY,
    data       JSONB NOT NULL,
    event_time TIMESTAMPTZ
);
"""


def _ensure_state_schema(conn: psycopg.Connection) -> None:
    conn.execute(STATE_DDL)  # type: ignore[arg-type]


def _ensure_run_events_schema(conn: psycopg.Connection) -> None:
    conn.execute(RUN_EVENTS_DDL)  # type: ignore[arg-type]


def load_state(db_url: str) -> dict[str, Any]:
    if not db_url:
        return {
            "processed": {},
            "feed_cursor": {},
            "feed_failures": {},
        }

    with psycopg.connect(db_url) as conn:
        _ensure_state_schema(conn)

        processed: dict[str, Any] = {}
        with conn.cursor() as cur:
            cur.execute("SELECT id, data FROM processed_items")
            for row in cur.fetchall():
                processed[row[0]] = row[1]

        feed_cursor: dict[str, Any] = {}
        with conn.cursor() as cur:
            cur.execute("SELECT feed_key, cursor_at FROM feed_cursors")
            for row in cur.fetchall():
                feed_cursor[row[0]] = row[1]

        feed_failures: dict[str, Any] = {}
        with conn.cursor() as cur:
            cur.execute("SELECT feed_key, data FROM feed_failures")
            for row in cur.fetchall():
                feed_failures[row[0]] = row[1]

    return {
        "processed": processed,
        "feed_cursor": feed_cursor,
        "feed_failures": feed_failures,
    }


def save_state(db_url: str, state: dict[str, Any]) -> None:
    if not db_url:
        return

    processed: dict[str, Any] = state.get("processed", {})
    feed_cursor: dict[str, Any] = state.get("feed_cursor", {})
    feed_failures: dict[str, Any] = state.get("feed_failures", {})

    with psycopg.connect(db_url) as conn:
        _ensure_state_schema(conn)

        with conn.cursor() as cur:
            if processed:
                cur.executemany(
                    """
                    INSERT INTO processed_items (id, data)
                    VALUES (%s, %s)
                    ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data
                    """,
                    [(k, json.dumps(v, ensure_ascii=False)) for k, v in processed.items()],
                )

            if feed_cursor:
                cur.executemany(
                    """
                    INSERT INTO feed_cursors (feed_key, cursor_at)
                    VALUES (%s, %s)
                    ON CONFLICT (feed_key) DO UPDATE SET cursor_at = EXCLUDED.cursor_at
                    """,
                    list(feed_cursor.items()),
                )

            if feed_failures:
                cur.executemany(
                    """
                    INSERT INTO feed_failures (feed_key, data)
                    VALUES (%s, %s)
                    ON CONFLICT (feed_key) DO UPDATE SET data = EXCLUDED.data
                    """,
                    [(k, json.dumps(v, ensure_ascii=False)) for k, v in feed_failures.items()],
                )

        conn.commit()


def _run_event_key(event: dict[str, Any]) -> str:
    key_obj = {k: event.get(k, "") for k in ("run_id", "id", "status", "time", "url")}
    return hashlib.sha256(json.dumps(key_obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def save_run_events(db_url: str, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    with psycopg.connect(db_url) as conn:
        _ensure_run_events_schema(conn)
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO run_events (event_key, data, event_time)
                VALUES (%s, %s, %s::timestamptz)
                ON CONFLICT (event_key) DO UPDATE SET data = EXCLUDED.data
                """,
                [(_run_event_key(e), json.dumps(e, ensure_ascii=False), e.get("time")) for e in events],
            )
        conn.commit()
