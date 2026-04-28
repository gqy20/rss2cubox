#!/usr/bin/env python3
"""临时脚本：将 IC API 的数据迁移到本地 PostgreSQL

Usage:
    uv run python scripts/migrate_ic_to_local.py

此脚本只运行一次，用于填充本地数据库。
迁移完成后，本地数据库可以作为查询使用，但去重仍以 IC API 为准。
"""
import os
import sys
from pathlib import Path

import psycopg
import requests

# 确保 src 目录在 path 中
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rss2cubox.db_client import save_articles, ARTICLES_SCHEMA


IC_API_URL = os.getenv("IC_API_URL", "").strip()
LOCAL_DB_URL = os.getenv("LOCAL_DB_URL", "").strip()


def fetch_all_ic_articles(api_url: str, page_size: int = 100) -> list[dict]:
    """从 IC API 分页获取所有文章。"""
    if not api_url:
        return []

    base_url = api_url.strip().rstrip("/")
    # 移除 batch 路径（如果有）
    base_url = base_url.replace("/api/v1/articles/batch", "")

    all_articles = []
    offset = 0

    while True:
        resp = requests.get(
            f"{base_url}/api/v1/articles",
            params={
                "limit": page_size,
                "offset": offset,
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        items = payload.get("data", {}).get("list", [])
        if not isinstance(items, list) or not items:
            break

        for item in items:
            if not isinstance(item, dict):
                continue
            all_articles.append(item)

        if len(items) < page_size:
            break
        offset += page_size
        print(f"  已获取 {len(all_articles)} 条...")

    return all_articles


def main():
    if not LOCAL_DB_URL:
        print("错误：LOCAL_DB_URL 未设置")
        sys.exit(1)

    if not IC_API_URL:
        print("错误：IC_API_URL 未设置")
        sys.exit(1)

    print(f"IC API: {IC_API_URL}")
    print(f"Local DB: {LOCAL_DB_URL}")
    print()

    # 先建表/检查表结构
    print("检查并创建 articles 表...")
    with psycopg.connect(LOCAL_DB_URL) as conn:
        cur = conn.cursor()
        # 检查 importance_score 列是否存在
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'articles' AND column_name = 'importance_score'
        """)
        if not cur.fetchone():
            print("添加 importance_score 列...")
            cur.execute("ALTER TABLE articles ADD COLUMN importance_score INTEGER DEFAULT 3")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_importance_score ON articles(importance_score)")
            conn.commit()
            print("列添加完成")
        else:
            print("表结构已是最新")
        # 确保 global_insights 表也存在
        cur.execute(ARTICLES_SCHEMA)
        conn.commit()
    print("表检查完成")
    print()

    # 获取 IC 数据
    print("从 IC API 获取数据...")
    articles = fetch_all_ic_articles(IC_API_URL)
    print(f"获取到 {len(articles)} 条记录")
    print()

    if not articles:
        print("没有数据需要迁移")
        return

    # 转换为 save_articles 需要的格式
    def to_article(item: dict) -> dict:
        url = str(item.get("url", "")).strip()
        # 生成稳定的 id
        import hashlib
        eid = hashlib.md5(url.encode()).hexdigest() if url else str(item.get("id", ""))
        return {
            "id": eid,
            "source_type": str(item.get("source_type", "rss")),
            "source_feed_id": str(item.get("source_feed_id", "")),
            "source_feed_name": str(item.get("source_feed_name", "")),
            "source_article_id": str(item.get("source_article_id", "")),
            "title": str(item.get("title", "")),
            "url": url,
            "pic_url": str(item.get("pic_url", "")),
            "description": str(item.get("description", "")),
            "publish_time": str(item.get("publish_time", "")),
            "tags": item.get("tags", []),
            "importance_score": 3,  # 默认值，迁移数据没有重要性评分
            "reason": str(item.get("reason", "")),
            "actionable": str(item.get("actionable", "")),
            "hidden_signal": str(item.get("hidden_signal", "")),
        }

    # 批量保存
    print("写入本地数据库...")
    batch_size = 100
    saved = 0
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        article_batch = [to_article(item) for item in batch]
        count = save_articles(article_batch, db_url=LOCAL_DB_URL)
        saved += count
        print(f"  已保存 {saved}/{len(articles)}")

    print()
    print(f"迁移完成！共保存 {saved} 条记录到本地数据库")


if __name__ == "__main__":
    main()
