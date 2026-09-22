#!/usr/bin/env python
"""初始化本地 PostgreSQL schema（幂等）。

用法:
    uv run python scripts/init_local_db.py                 # 建主链路全部表
    uv run python scripts/init_local_db.py --with-legacy    # 额外建 legacy 表
    uv run python scripts/init_local_db.py --db-url postgresql://...
    uv run python scripts/init_local_db.py --dry-run        # 只看要执行什么，不连库

连接串优先级: --db-url > DATABASE_URL 环境变量 > 根目录 .env
所有 DDL 均为 CREATE TABLE IF NOT EXISTS，可重复执行。
"""
import argparse
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent

# 主链路 schema：db_client 各模块在运行时也会惰性建表，这里一次性建全
MAIN_SCHEMAS = [
    ("articles", "rss2cubox.db_client.articles", "ARTICLES_SCHEMA"),
    ("global_insights", "rss2cubox.db_client.insights", "GLOBAL_INSIGHTS_SCHEMA"),
    ("daily_reports", "rss2cubox.db_client.reports", "DAILY_REPORTS_SCHEMA"),
    ("signal_clusters / trend_predictions / ...", "rss2cubox.db_client.predictions", "PREDICTION_LOOP_SCHEMA"),
]

# legacy schema：仅供历史迁移与排障脚本使用（README 第 9 节）
LEGACY_SCHEMAS = [
    ("processed_items / feed_cursors / feed_failures", "rss2cubox.legacy.db", "STATE_DDL"),
    ("run_events", "rss2cubox.legacy.db", "RUN_EVENTS_DDL"),
]


def _load_schema(module_path: str, attr: str) -> str:
    import importlib

    module = importlib.import_module(module_path)
    ddl = getattr(module, attr, "")
    if not ddl:
        raise RuntimeError(f"{module_path}.{attr} 为空")
    return ddl


def _list_tables(conn) -> list[str]:
    cur = conn.cursor()
    cur.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
    )
    return [row[0] for row in cur.fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化本地 PostgreSQL schema")
    parser.add_argument("--db-url", default=None, help="覆盖 DATABASE_URL")
    parser.add_argument("--with-legacy", action="store_true", help="同时建 legacy 表")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不连库")
    args = parser.parse_args()

    # 与项目其它模块一致：.env 覆盖已有环境变量
    load_dotenv(ROOT_DIR / ".env", override=True)

    db_url = (args.db_url or os.getenv("DATABASE_URL", "")).strip()
    if not db_url:
        print("✗ 未找到连接串：请用 --db-url 指定，或在 .env 里设置 DATABASE_URL", file=sys.stderr)
        return 2

    # 打印时隐去密码
    safe_url = db_url
    if "@" in safe_url and "://" in safe_url:
        scheme, rest = safe_url.split("://", 1)
        creds, host = rest.split("@", 1)
        user = creds.split(":", 1)[0]
        safe_url = f"{scheme}://{user}:***@{host}"

    targets = MAIN_SCHEMAS + (LEGACY_SCHEMAS if args.with_legacy else [])

    print(f"[db-init] 目标库: {safe_url}")
    print(f"[db-init] 待应用 schema ({len(targets)} 组):")
    for label, module_path, attr in targets:
        print(f"  - {label:45s} <- {module_path}.{attr}")

    if args.dry_run:
        print("[db-init] --dry-run，未连接数据库")
        return 0

    try:
        with psycopg.connect(db_url, connect_timeout=10) as conn:
            cur = conn.cursor()
            for label, module_path, attr in targets:
                ddl = _load_schema(module_path, attr)
                cur.execute(ddl)
                print(f"  ✓ {label}")
            conn.commit()

            tables = _list_tables(conn)
            print(f"[db-init] 完成，public schema 现有 {len(tables)} 张表:")
            for name in tables:
                cur.execute(f'SELECT COUNT(*) FROM "{name}"')
                count = cur.fetchone()[0]
                print(f"  {name:32s} {count:>8d} 行")
    except psycopg.OperationalError as e:
        print(f"✗ 连接失败: {e}", file=sys.stderr)
        print("  提示: 先执行 `make db` 启动本地 PostgreSQL 容器", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"✗ 初始化失败: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
