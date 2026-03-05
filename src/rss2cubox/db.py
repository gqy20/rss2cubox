"""
Neon (PostgreSQL) 后端。

接口：
  load_state / save_state   — 替换 state.json 读写
  save_run_events           — 写入本次运行事件
  save_global_insights      — 写入全局 Agent 分析结果（保留历史）
  load_global_insights      — 读取最新全局分析
  load_all_global_insights  — 读取所有历史全局分析
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg

DDL = """
CREATE TABLE IF NOT EXISTS sent_items (
    id   TEXT PRIMARY KEY,
    url  TEXT NOT NULL,
    ts   TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_results (
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

CREATE TABLE IF NOT EXISTS run_events (
    event_key  TEXT PRIMARY KEY,
    data       JSONB NOT NULL,
    event_time TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS global_insights (
    id           SERIAL PRIMARY KEY,
    generated_at TIMESTAMPTZ NOT NULL,
    data         JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_global_insights_generated_at ON global_insights(generated_at DESC);
"""


def _ensure_schema(conn: psycopg.Connection) -> None:
    conn.execute(DDL)  # type: ignore[arg-type]
    _migrate_global_insights_table(conn)


def _migrate_global_insights_table(conn: psycopg.Connection) -> None:
    """迁移旧的 global_insights 表结构（singleton -> id）"""
    with conn.cursor() as cur:
        # 检查是否存在 singleton 列（旧表结构）
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'global_insights' AND column_name = 'singleton'
        """)
        if cur.fetchone():
            # 旧表存在，需要迁移
            cur.execute("SELECT generated_at, data FROM global_insights LIMIT 1")
            old_row = cur.fetchone()
            # 删除旧表
            cur.execute("DROP TABLE global_insights")
            # 创建新表
            cur.execute("""
                CREATE TABLE global_insights (
                    id           SERIAL PRIMARY KEY,
                    generated_at TIMESTAMPTZ NOT NULL,
                    data         JSONB NOT NULL
                )
            """)
            cur.execute("CREATE INDEX idx_global_insights_generated_at ON global_insights(generated_at DESC)")
            # 如果有旧数据，迁移到新表
            if old_row:
                cur.execute(
                    "INSERT INTO global_insights (generated_at, data) VALUES (%s, %s)",
                    (old_row[0], json.dumps(old_row[1], ensure_ascii=False))
                )


def load_state(db_url: str) -> dict[str, Any]:
    with psycopg.connect(db_url) as conn:
        _ensure_schema(conn)

        sent: dict[str, Any] = {}
        with conn.cursor() as cur:
            cur.execute("SELECT id, url, ts FROM sent_items")
            for row in cur.fetchall():
                sent[row[0]] = {"url": row[1], "ts": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2])}

        ai: dict[str, Any] = {}
        with conn.cursor() as cur:
            cur.execute("SELECT id, data FROM ai_results")
            for row in cur.fetchall():
                ai[row[0]] = row[1]

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
        "sent": sent,
        "ai": ai,
        "feed_cursor": feed_cursor,
        "feed_failures": feed_failures,
    }


def save_state(db_url: str, state: dict[str, Any]) -> None:
    sent: dict[str, Any] = state.get("sent", {})
    ai: dict[str, Any] = state.get("ai", {})
    feed_cursor: dict[str, Any] = state.get("feed_cursor", {})
    feed_failures: dict[str, Any] = state.get("feed_failures", {})

    with psycopg.connect(db_url) as conn:
        _ensure_schema(conn)

        with conn.cursor() as cur:
            # sent_items
            if sent:
                cur.executemany(
                    """
                    INSERT INTO sent_items (id, url, ts)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET url = EXCLUDED.url, ts = EXCLUDED.ts
                    """,
                    [(k, v["url"], v["ts"]) for k, v in sent.items()],
                )

            # ai_results
            if ai:
                cur.executemany(
                    """
                    INSERT INTO ai_results (id, data)
                    VALUES (%s, %s)
                    ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data
                    """,
                    [(k, json.dumps(v, ensure_ascii=False)) for k, v in ai.items()],
                )

            # feed_cursors
            if feed_cursor:
                cur.executemany(
                    """
                    INSERT INTO feed_cursors (feed_key, cursor_at)
                    VALUES (%s, %s)
                    ON CONFLICT (feed_key) DO UPDATE SET cursor_at = EXCLUDED.cursor_at
                    """,
                    list(feed_cursor.items()),
                )

            # feed_failures
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
        _ensure_schema(conn)
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


def save_global_insights(db_url: str, payload: dict[str, Any]) -> None:
    """保存全局分析结果（保留历史，不覆盖）"""
    with psycopg.connect(db_url) as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO global_insights (generated_at, data)
                VALUES (%s::timestamptz, %s)
                """,
                (payload.get("generated_at"), json.dumps(payload, ensure_ascii=False)),
            )
        conn.commit()


def load_global_insights(db_url: str) -> dict[str, Any] | None:
    """读取最新全局分析"""
    with psycopg.connect(db_url) as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT data FROM global_insights ORDER BY generated_at DESC LIMIT 1")
            row = cur.fetchone()
    return row[0] if row else None


def load_all_global_insights(db_url: str, limit: int = 30) -> list[dict[str, Any]]:
    """读取所有历史全局分析（按时间倒序）"""
    with psycopg.connect(db_url) as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, generated_at, data FROM global_insights ORDER BY generated_at DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "generated_at": row[1].isoformat() if hasattr(row[1], "isoformat") else str(row[1]),
            **row[2],
        }
        for row in rows
    ]
