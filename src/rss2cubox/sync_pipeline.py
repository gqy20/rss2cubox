from __future__ import annotations

import calendar
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"[WARN] invalid {name}={raw!r}, fallback to {default}", flush=True)
        return default


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"[WARN] invalid {name}={raw!r}, fallback to {default}", flush=True)
        return default


def load_state(state_file: Path) -> dict:
    if not state_file.exists():
        return {"processed": {}}
    with state_file.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state_file: Path, state: dict) -> None:
    with state_file.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def save_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")


def _normalize_url(url: str) -> str:
    """清理 URL，移除常见的追踪参数和 fragment"""
    if not url:
        return ""

    try:
        parsed = urlparse(url)
        # 移除追踪参数
        tracking_params = {
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
            "fbclid",
            "gclid",
            "ref",
            "referrer",
            "source_id",
            "_ga",
            "_gl",
            "mc_cid",
            "mc_eid",
        }
        query = parse_qs(parsed.query, keep_blank_values=True)
        query = {k: v for k, v in query.items() if k.lower() not in tracking_params}

        # 移除 fragment
        normalized = urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(query, doseq=True) if query else "",
                "",
            )
        )
        return normalized
    except Exception:  # noqa: BLE001
        return url


def stable_id(entry: dict) -> str:
    # 优先使用清理后的 URL
    link = entry.get("link", "").strip()
    if link:
        normalized = _normalize_url(link)
        if normalized:
            return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    # 降级：使用 id/guid
    identifier = entry.get("id") or entry.get("guid")
    if identifier:
        raw = str(identifier)
    else:
        # 最后的降级方案
        raw = entry.get("title") or ""

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def text_blob(entry: dict) -> str:
    return " ".join(
        [
            entry.get("title", "") or "",
            entry.get("summary", "") or "",
            entry.get("description", "") or "",
            entry.get("link", "") or "",
        ]
    ).lower()


def passes_filter(entry: dict, include_keywords: list[str], exclude_keywords: list[str]) -> bool:
    blob = text_blob(entry)
    if include_keywords and not any(k.lower() in blob for k in include_keywords):
        return False
    if exclude_keywords and any(k.lower() in blob for k in exclude_keywords):
        return False
    return True


def parse_entry_timestamp(entry: dict) -> datetime | None:
    for key in ("updated_parsed", "published_parsed"):
        ts = entry.get(key)
        if ts:
            try:
                return datetime.fromtimestamp(calendar.timegm(ts), tz=timezone.utc)
            except Exception:  # noqa: BLE001
                pass
    for key in ("updated", "published"):
        raw = str(entry.get(key, "")).strip()
        if not raw:
            continue
        parsed = parse_iso_datetime(raw)
        if parsed is None:
            try:
                parsed = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    return None


def parse_iso_datetime(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def feed_failure_backoff_seconds(
    failure_count: int,
    base_seconds: int,
    max_seconds: int,
) -> int:
    return min(max_seconds, base_seconds * (2 ** max(0, failure_count - 1)))


def feed_is_circuit_open(feed_failure_state: dict[str, Any], now_utc: datetime) -> tuple[bool, int]:
    until_dt = parse_iso_datetime(str(feed_failure_state.get("cooldown_until", "")))
    if until_dt is None or until_dt <= now_utc:
        return False, 0
    remaining = max(0, int((until_dt - now_utc).total_seconds()))
    return True, remaining


def dedupe_run_candidates(
    candidates: list[dict[str, Any]],
    per_feed_drop_reasons: dict[str, dict[str, int]],
) -> tuple[list[dict[str, Any]], int]:
    run_seen: set[str] = set()
    unique_candidates: list[dict[str, Any]] = []
    run_deduped = 0
    for item in candidates:
        eid = str(item.get("eid", "")).strip()
        if not eid:
            continue
        if eid in run_seen:
            run_deduped += 1
            source_feed = str(item.get("source_feed", "unknown"))
            drop_by_feed = per_feed_drop_reasons.setdefault(source_feed, {})
            drop_by_feed["run_deduped"] = drop_by_feed.get("run_deduped", 0) + 1
            continue
        run_seen.add(eid)
        unique_candidates.append(item)
    return unique_candidates, run_deduped


def load_local_state(
    db_url: str | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Load processed articles state from local PostgreSQL database.

    Used for deduplication when IC_API_URL is not configured.

    Args:
        db_url: PostgreSQL connection URL. If None, reads from LOCAL_DB_URL env.

    Returns:
        tuple:
            - processed: dict[eid -> record] with id and exported fields
            - feed_cursor: dict[source_feed_id -> latest_publish_time_iso]
    """
    from rss2cubox.db_client import get_all_article_ids, get_feed_cursors

    if db_url is None:
        db_url = os.getenv("LOCAL_DB_URL", "").strip()

    if not db_url:
        return {}, {}

    article_ids = get_all_article_ids(db_url)

    processed: dict[str, dict[str, Any]] = {}
    for eid in article_ids:
        processed[eid] = {
            "id": eid,
            "exported": True,
        }

    feed_cursor = get_feed_cursors(db_url)

    return processed, feed_cursor


def load_ic_state(
    *,
    api_url: str | None,
    source_type: str,
    request_get: Any,
    page_size: int = 100,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    # Priority: local database > IC API
    processed, feed_cursor = load_local_state()
    if processed:
        return processed, feed_cursor

    if not api_url:
        return {}, {}

    base_url = re.sub(r"/api/v1/articles/batch/?$", "", api_url.strip())
    if not base_url:
        return {}, {}

    processed: dict[str, dict[str, Any]] = {}
    feed_cursor: dict[str, str] = {}
    offset = 0

    while True:
        response = request_get(
            f"{base_url}/api/v1/articles",
            params={
                "source_type": source_type,
                "limit": page_size,
                "offset": offset,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("data", {}).get("list", [])
        if not isinstance(items, list) or not items:
            break

        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            if not url:
                continue
            eid = stable_id({"link": url})
            publish_time = str(item.get("publish_time", "")).strip()
            source_feed_id = str(item.get("source_feed_id", "")).strip()
            processed[eid] = {
                "id": eid,
                "url": url,
                "publish_time": publish_time,
                "source_feed_id": source_feed_id,
                "exported": True,
            }
            publish_dt = parse_iso_datetime(publish_time)
            prev_dt = parse_iso_datetime(feed_cursor.get(source_feed_id, ""))
            if source_feed_id and publish_dt is not None and (prev_dt is None or publish_dt > prev_dt):
                feed_cursor[source_feed_id] = publish_dt.isoformat()

        if len(items) < page_size:
            break
        offset += page_size

    return processed, feed_cursor


def build_processed_article(
    *,
    item: dict[str, Any],
    analysis: dict[str, Any],
    now_iso: str,
    source_type: str,
) -> dict[str, Any]:
    eid = str(item.get("eid", "")).strip()
    source_feed_id = str(item.get("source_feed", "")).strip()
    source_feed_name = str(item.get("source_label", "")).strip() or source_feed_id or "unknown"
    source_article_id = str(item.get("source_article_id", "")).strip() or eid
    core_event = str(analysis.get("core_event", "")).strip()
    description = core_event or str(item.get("description", "")).strip()
    tags = analysis.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    publish_time = str(item.get("publish_time", "")).strip()

    article = {
        "id": eid,
        "source_type": source_type,
        "source_feed_id": source_feed_id,
        "source_feed_name": source_feed_name,
        "source_article_id": source_article_id,
        "title": str(item.get("title", "")).strip(),
        "url": str(item.get("url", "")).strip(),
        "pic_url": str(item.get("cover_url", "")).strip(),
        "description": description,
        "publish_time": publish_time,
        "tags": tags,
        "importance_score": analysis.get("importance_score", 3),
        "reason": str(analysis.get("reason", "")).strip(),
        "actionable": str(analysis.get("actionable", "")).strip(),
        "hidden_signal": str(analysis.get("hidden_signal", "")).strip(),
        "exported": False,
        "exported_at": "",
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    content_source = str(analysis.get("content_source", "")).strip()
    if content_source in {"full_text", "summary_only"}:
        article["content_source"] = content_source

    for key, upper in (
        ("signal_type", 12),
        ("evidence_type", 12),
        ("evidence_strength", 5),
        ("novelty_score", 5),
        ("impact_horizon", 5),
        ("market_stage", 6),
        ("confidence", 5),
    ):
        value = analysis.get(key)
        if isinstance(value, int) and 1 <= value <= upper:
            article[key] = value

    audience = analysis.get("audience", [])
    if isinstance(audience, list):
        article["audience"] = [
            value for value in audience
            if isinstance(value, int) and 1 <= value <= 8
        ][:3]

    for key in ("entities", "watch_keywords"):
        values = analysis.get(key, [])
        if isinstance(values, list):
            article[key] = [str(value).strip() for value in values if str(value).strip()][:8]

    for key in ("cluster_hint", "prediction", "disconfirming_evidence"):
        value = str(analysis.get(key, "")).strip()
        if value:
            article[key] = value

    enrich_meta = analysis.get("enrich_meta")
    article["enrich_meta"] = enrich_meta if isinstance(enrich_meta, dict) else {}
    return article


def has_signal_analysis(analysis: dict[str, Any] | None) -> bool:
    if not analysis:
        return False
    return any(str(analysis.get(key, "")).strip() for key in ("core_event", "reason", "hidden_signal", "actionable"))


def collect_pending_articles(processed_state: dict[str, Any]) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    for row in processed_state.values():
        if not isinstance(row, dict):
            continue
        if bool(row.get("exported", False)):
            continue
        pending.append(row)
    pending.sort(key=lambda row: str(row.get("created_at", "")))
    return pending


def mark_articles_exported(
    processed_state: dict[str, Any],
    article_ids: list[str],
    exported_at: str,
) -> None:
    for article_id in article_ids:
        row = processed_state.get(article_id)
        if not isinstance(row, dict):
            continue
        row["exported"] = True
        row["exported_at"] = exported_at
        row["updated_at"] = exported_at


def post_articles_batch(
    *,
    api_url: str | None,
    request_post: Any,
    articles: list[dict[str, Any]],
) -> str:
    if not api_url:
        raise RuntimeError("IC_API_URL is missing.")
    response = request_post(api_url, json={"articles": articles}, timeout=30)
    response.raise_for_status()
    return response.text


def post_articles_in_chunks(
    *,
    api_url: str | None,
    request_post: Any,
    articles: list[dict[str, Any]],
    chunk_size: int,
) -> list[str]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")

    responses: list[str] = []
    for start in range(0, len(articles), chunk_size):
        batch = articles[start : start + chunk_size]
        responses.append(
            post_articles_batch(
                api_url=api_url,
                request_post=request_post,
                articles=batch,
            )
        )
    return responses
