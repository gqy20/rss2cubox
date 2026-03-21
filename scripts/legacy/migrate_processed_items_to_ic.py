#!/usr/bin/env python3
"""LEGACY: 从旧 Neon processed_items 表迁移数据到 ic articles batch API。

仅用于一次性历史回填，不属于当前主同步链路。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg
import requests


def load_local_env_file(env_file: Path = Path(".env")) -> None:
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, value.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", default=os.getenv("NEON_DATABASE_URL", "").strip())
    parser.add_argument("--api-url", default=os.getenv("IC_API_URL", "").strip())
    parser.add_argument("--source-type", default=os.getenv("IC_SOURCE_TYPE", "gqy").strip() or "gqy")
    parser.add_argument("--batch-size", type=int, default=max(1, int(os.getenv("MIGRATE_BATCH_SIZE", "100"))))
    parser.add_argument("--only-pushed", action="store_true", help="只迁移旧库里 pushed/exported 的记录")
    parser.add_argument("--dry-run", action="store_true", help="只打印统计，不实际 POST")
    return parser.parse_args()


def should_migrate(row: dict[str, Any], *, only_pushed: bool) -> bool:
    if not only_pushed:
        return bool(str(row.get("url", "")).strip() and str(row.get("title", "")).strip())
    return bool(
        row.get("exported", False)
        or row.get("pushed", False)
        or str(row.get("status", "")).strip().lower() == "pushed"
    )


def normalize_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(tag).strip() for tag in value if str(tag).strip()]


def to_ic_article(row: dict[str, Any], *, source_type: str) -> dict[str, Any] | None:
    url = str(row.get("url", "")).strip()
    title = str(row.get("title", "")).strip()
    if not url or not title:
        return None

    source_feed_id = str(row.get("source_feed_id", row.get("source_feed", ""))).strip()
    source_feed_name = str(row.get("source_feed_name", row.get("source_label", ""))).strip() or source_feed_id or "unknown"
    source_article_id = str(row.get("source_article_id", row.get("id", ""))).strip() or str(row.get("id", "")).strip()
    article_source_type = str(row.get("source_type", "")).strip() or source_type
    description = str(row.get("description", "")).strip() or str(row.get("core_event", "")).strip()
    publish_time = str(row.get("publish_time", row.get("time", ""))).strip()

    return {
        "source_type": article_source_type,
        "source_feed_id": source_feed_id,
        "source_feed_name": source_feed_name,
        "source_article_id": source_article_id,
        "title": title,
        "url": url,
        "pic_url": str(row.get("pic_url", row.get("cover_url", ""))).strip() or None,
        "description": description or None,
        "publish_time": publish_time or None,
        "tags": normalize_tags(row.get("tags", [])),
        "reason": str(row.get("reason", "")).strip() or None,
        "actionable": str(row.get("actionable", "")).strip() or None,
        "hidden_signal": str(row.get("hidden_signal", "")).strip() or None,
    }


def chunked(items: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    return [items[idx : idx + batch_size] for idx in range(0, len(items), batch_size)]


def load_processed_rows(db_url: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, data FROM processed_items ORDER BY id")
            for item_id, data in cur.fetchall():
                if isinstance(data, dict):
                    row = dict(data)
                else:
                    try:
                        row = json.loads(data)
                    except Exception:
                        continue
                row.setdefault("id", item_id)
                rows.append(row)
    return rows


def post_batch(api_url: str, articles: list[dict[str, Any]]) -> tuple[int, int]:
    response = requests.post(api_url, json={"articles": articles}, timeout=30)
    response.raise_for_status()
    payload = response.json() if response.content else {}
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    return int(data.get("inserted_count", 0)), int(data.get("skipped_count", 0))


def main() -> None:
    load_local_env_file()
    args = parse_args()

    if not args.db_url:
        print("ERROR: --db-url 或 NEON_DATABASE_URL 未设置", file=sys.stderr, flush=True)
        sys.exit(1)
    if not args.api_url and not args.dry_run:
        print("ERROR: --api-url 或 IC_API_URL 未设置", file=sys.stderr, flush=True)
        sys.exit(1)

    rows = load_processed_rows(args.db_url)
    seen_urls: set[str] = set()
    articles: list[dict[str, Any]] = []
    skipped = 0

    for row in rows:
        if not should_migrate(row, only_pushed=args.only_pushed):
            skipped += 1
            continue
        article = to_ic_article(row, source_type=args.source_type)
        if article is None:
            skipped += 1
            continue
        url = str(article.get("url", "")).strip()
        if url in seen_urls:
            skipped += 1
            continue
        seen_urls.add(url)
        articles.append(article)

    print(
        f"[prepare] rows={len(rows)} selected={len(articles)} skipped={skipped} batch_size={args.batch_size}",
        flush=True,
    )

    if args.dry_run:
        preview = articles[:3]
        print(json.dumps({"preview": preview, "total": len(articles)}, ensure_ascii=False, indent=2), flush=True)
        return

    total_inserted = 0
    total_skipped = 0
    for idx, batch in enumerate(chunked(articles, args.batch_size), start=1):
        inserted, skipped_count = post_batch(args.api_url, batch)
        total_inserted += inserted
        total_skipped += skipped_count
        print(
            f"[batch {idx}] size={len(batch)} inserted={inserted} skipped={skipped_count}",
            flush=True,
        )

    print(
        f"[done] selected={len(articles)} inserted={total_inserted} skipped={total_skipped}",
        flush=True,
    )


if __name__ == "__main__":
    main()
