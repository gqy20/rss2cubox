"""Congress.gov 立法适配器——美国 AI 法案动向进 articles。

为什么是适配器而不是 RSS：congress.gov API v3 没有关键词搜索端点，
替代做法是按 updateDate 倒序拉最新一页（250 条/次请求），客户端做
关键词过滤。额度消耗 4 请求/天（限额 5000/日）。

去重即幂等：法案条目 URL 稳定（congress.gov/bill/119th-congress/s/5576），
stable_id 生成后交给 save_articles 的 ON CONFLICT——已入库的法案自动跳过，
本版本不追踪后续立法动作（进展仍会出现在 RSS/媒体源里）。
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests

from rss2cubox.db_client import save_articles

API_BASE = "https://api.congress.gov/v3"
SOURCE_FEED_ID = "us-congress"
SOURCE_LABEL = "US Congress Bills（congress.gov API）"

# 客户端过滤：标题命中任一即保留。小写匹配。
KEYWORDS = (
    "artificial intelligence",
    "machine learning",
    "deepfake",
    "chatbot",
    "algorithmic",
    "autonomous vehicle",
    "autonomous weapon",
    " ai ",
    "semiconductor",
    "compute",
)


def _stable_id(url: str) -> str:
    return hashlib.sha256((url or "").strip().encode("utf-8")).hexdigest()


def fetch_ai_bills(
    *,
    api_key: str | None = None,
    congress: int | None = None,
    limit: int = 250,
    timeout: float = 20.0,
) -> list[dict[str, Any]]:
    """拉取最新更新的法案页并按关键词过滤，返回 articles 候选结构。"""
    api_key = (api_key or os.getenv("CONGRESS_API_KEY", "")).strip()
    if not api_key:
        return []
    congress = congress or int(os.getenv("CONGRESS_CONGRESS", "119"))
    url = (
        f"{API_BASE}/bill/{congress}"
        f"?api_key={api_key}&format=json&limit={min(max(limit, 1), 250)}"
        "&sort=updateDate+desc"
    )
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        bills = resp.json().get("bills", [])
    except requests.exceptions.RequestException as exc:  # noqa: BLE001
        logging.warning("congress_fetch failed: %s: %s", type(exc).__name__, str(exc)[:120])
        return []

    out: list[dict[str, Any]] = []
    for b in bills:
        title = str(b.get("title") or "").strip()
        if not title or not any(k in f" {title.lower()} " for k in KEYWORDS):
            continue
        action = b.get("latestAction") or {}
        action_text = str(action.get("text") or "").strip()
        bill_url = str(b.get("url") or "").split("?")[0].strip()  # api 条目页，转 congress.gov 展示页
        parts = bill_url.rstrip("/").split("/")[-2:]  # .../119th-congress/<type>/<number>
        slug = "/".join(parts) if len(parts) == 2 else ""
        display = (
            f"https://www.congress.gov/bill/{congress}th-congress/{slug}"
            if slug
            else "https://www.congress.gov/"
        )
        out.append({
            "id": _stable_id(display),
            "source_type": "us-congress",
            "source_feed_id": SOURCE_FEED_ID,
            "source_feed_name": SOURCE_LABEL,
            "source_article_id": f"{b.get('type')}-{b.get('number')}",
            "title": f"[美]{b.get('type')} {b.get('number')} · {title}"[:300],
            "url": display,
            "pic_url": "",
            "description": (action_text or title)[:500],
            "publish_time": str(action.get("actionDate") or datetime.now(timezone.utc).date()),
        })
    return out


def run(log_event: Any = None) -> int:
    """抓取并入库。返回新入库条数。未配 key 时静默跳过。"""
    candidates = fetch_ai_bills()
    if not candidates:
        if log_event:
            log_event("INFO", "congress_fetch_skipped", stage="congress", reason="no_candidates_or_key")
        return 0
    saved = save_articles(candidates)
    if log_event:
        log_event("INFO", "congress_fetch_done", stage="congress", filtered=len(candidates), saved=saved)
    return saved


if __name__ == "__main__":
    import json

    from dotenv import load_dotenv

    load_dotenv(".env", override=True)  # python -m 直跑时不会经过 runner 的 env 加载
    print(json.dumps({
        "event": "congress_fetch_main",
        "ts": datetime.now(timezone.utc).isoformat(),
        "saved": run(),
    }))
