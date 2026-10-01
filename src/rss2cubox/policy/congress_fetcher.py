"""Congress.gov 立法适配器——美国 AI 法案进政策管线（policy_documents）。

政策管线统一整合层的一员（2026-10-01 从科技管线 articles 侧迁入）：
congress.gov API v3 没有关键词搜索端点，替代做法是按 updateDate 倒序拉
最新一页（250 条/次请求），客户端做关键词过滤。额度消耗 4 请求/天
（限额 5000/日），随政策 cron（07:30/19:30）节奏运行。

幂等：法案展示 URL 稳定，stable_policy_id 生成 doc_id 后交给
save_policy_documents 的 ON CONFLICT——已入库的法案自动跳过更新。
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import Any

import requests

from rss2cubox.policy.engine import PolicyItem
from rss2cubox.policy.store import save_policy_documents

API_BASE = "https://api.congress.gov/v3"
SITE_KEY = "us_congress"
SITE_NAME = "US Congress 国会立法"

# 客户端过滤：标题命中任一即保留。小写匹配，前后空格保证词边界。
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


def fetch_ai_bills(
    *,
    api_key: str | None = None,
    congress: int | None = None,
    limit: int = 250,
    timeout: float = 20.0,
) -> list[PolicyItem]:
    """拉取最新更新的法案页并按关键词过滤，返回 PolicyItem 列表。"""
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

    out: list[PolicyItem] = []
    for b in bills:
        title = str(b.get("title") or "").strip()
        if not title or not any(k in f" {title.lower()} " for k in KEYWORDS):
            continue
        action = b.get("latestAction") or {}
        bill_url = str(b.get("url") or "").split("?")[0].strip()
        parts = bill_url.rstrip("/").split("/")[-2:]  # .../119th-congress/<type>/<number>
        slug = "/".join(parts) if len(parts) == 2 else ""
        display = (
            f"https://www.congress.gov/bill/{congress}th-congress/{slug}"
            if slug
            else ""
        )
        if not display:
            continue
        try:
            published = date.fromisoformat(str(action.get("actionDate") or ""))
        except ValueError:
            published = None
        out.append(
            PolicyItem(
                site_key=SITE_KEY,
                title=f"{b.get('type')} {b.get('number')} · {title}"[:300],
                url=display,
                published_at=(
                    datetime(published.year, published.month, published.day, tzinfo=timezone.utc)
                    if published
                    else None
                ),
            )
        )
    return out


def run(log_event: Any = None) -> int:
    """抓取并入库 policy_documents。返回写入行数；未配 key 静默跳过。"""
    items = fetch_ai_bills()
    if not items:
        if log_event:
            log_event("INFO", "congress_fetch_skipped", stage="policy_fetch", reason="no_candidates_or_key")
        return 0
    stats = save_policy_documents(items, site_name=SITE_NAME, level="national", region="美国")
    if log_event:
        log_event(
            "INFO",
            "congress_fetch_done",
            stage="policy_fetch",
            filtered=len(items),
            inserted=stats.get("inserted", 0),
            updated=stats.get("updated", 0),
        )
    return stats.get("inserted", 0) + stats.get("updated", 0)


if __name__ == "__main__":
    import json

    from dotenv import load_dotenv

    load_dotenv(".env", override=True)  # python -m 直跑时不会经过 runner 的 env 加载
    print(json.dumps({
        "event": "congress_fetch_main",
        "ts": datetime.now(timezone.utc).isoformat(),
        "written": run(),
    }))
