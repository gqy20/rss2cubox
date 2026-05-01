"""
Neon global insights backend.

This module now only owns the still-active `global_insights` table.
Legacy state/event helpers were moved to `rss2cubox.legacy.db`.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg

GLOBAL_INSIGHTS_DDL = """
CREATE TABLE IF NOT EXISTS global_insights (
    id           SERIAL PRIMARY KEY,
    generated_at TIMESTAMPTZ NOT NULL,
    data         JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_global_insights_generated_at ON global_insights(generated_at DESC);
"""


def _ensure_global_insights_schema(conn: psycopg.Connection) -> None:
    conn.execute(GLOBAL_INSIGHTS_DDL)  # type: ignore[arg-type]
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
                # old_row[1] is a JSON string from old TEXT column, parse it first
                old_data = old_row[1]
                if isinstance(old_data, str):
                    old_data = json.loads(old_data)
                cur.execute(
                    "INSERT INTO global_insights (generated_at, data) VALUES (%s, %s)",
                    (old_row[0], old_data)
                )

def save_global_insights(db_url: str, payload: dict[str, Any]) -> None:
    """保存全局分析结果（保留历史，不覆盖）"""
    with psycopg.connect(db_url) as conn:
        _ensure_global_insights_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO global_insights (generated_at, data)
                VALUES (%s::timestamptz, %s)
                """,
                (payload.get("generated_at"), payload),
            )
        conn.commit()


def load_global_insights(db_url: str) -> dict[str, Any] | None:
    """读取最新全局分析"""
    with psycopg.connect(db_url) as conn:
        _ensure_global_insights_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT data FROM global_insights ORDER BY generated_at DESC LIMIT 1")
            row = cur.fetchone()
    return row[0] if row else None


def load_all_global_insights(db_url: str, limit: int = 30) -> list[dict[str, Any]]:
    """读取所有历史全局分析（按时间倒序）"""
    with psycopg.connect(db_url) as conn:
        _ensure_global_insights_schema(conn)
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


def fix_duplicate_encoded_insights(db_url: str) -> int:
    """修复双重 JSON 编码的 global_insights 数据，返回修复的记录数"""
    import json as _json

    fixed = 0
    with psycopg.connect(db_url) as conn:
        _ensure_global_insights_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT id, generated_at, data FROM global_insights ORDER BY id")
            rows = cur.fetchall()

        for row in rows:
            row_id, generated_at, data = row
            # 如果 data 是字符串（双重编码），解析后重新保存
            if isinstance(data, str):
                try:
                    parsed = _json.loads(data)
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE global_insights SET data = %s WHERE id = %s",
                            (parsed, row_id),
                        )
                    conn.commit()
                    fixed += 1
                    print(f"Fixed record id={row_id}")
                except _json.JSONDecodeError:
                    print(f"Failed to parse record id={row_id}: {data[:100]}")

    return fixed
