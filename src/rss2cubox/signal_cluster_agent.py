"""Rule-based Signal Cluster Agent.

This is the first deterministic implementation of the cluster agent. It turns
enriched article rows into stable signal clusters that later prediction agents
can reason over. A future version can replace the grouping step with embeddings
or an Agent SDK review pass without changing the output contract.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any


def normalize_cluster_label(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "unknown"


def build_cluster_key(article: dict[str, Any]) -> str:
    signal_type = article.get("signal_type")
    if not isinstance(signal_type, int) or signal_type < 1:
        signal_type = 12

    raw_label = (
        str(article.get("cluster_hint") or "").strip()
        or _first_text(article.get("tags"))
        or str(article.get("title") or "").strip()
        or "unknown"
    )
    return f"{signal_type}:{normalize_cluster_label(raw_label)}"


def run_signal_cluster_agent(
    articles: list[dict[str, Any]],
    *,
    existing_clusters: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, list[dict[str, Any]]]:
    now_dt = now or datetime.now(timezone.utc)
    existing_by_key = {str(c.get("cluster_key") or c.get("normalized_label") or ""): c for c in (existing_clusters or [])}

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for article in articles:
        if not article.get("id"):
            continue
        grouped[build_cluster_key(article)].append(article)

    clusters: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    for cluster_key, items in grouped.items():
        label = _cluster_label(items, cluster_key)
        signal_type = _first_int(items, "signal_type") or 12
        first_seen, last_seen = _date_range(items)
        recent_count = sum(1 for item in items if _parse_dt(item.get("publish_time")) and _parse_dt(item.get("publish_time")) >= now_dt - timedelta(days=7))
        prev_count = sum(
            1
            for item in items
            if (dt := _parse_dt(item.get("publish_time")))
            and now_dt - timedelta(days=14) <= dt < now_dt - timedelta(days=7)
        )
        article_count = len(items)
        source_names = {str(item.get("source_feed_name") or item.get("source") or "").strip() for item in items}
        source_names.discard("")
        volume_30d_avg = max(article_count / 4.0, 0.25)
        burst_ratio = round(recent_count / volume_30d_avg, 2)
        existing = existing_by_key.get(cluster_key)

        cluster = {
            "cluster_key": cluster_key,
            "label": label,
            "normalized_label": cluster_key.split(":", 1)[1],
            "signal_type": signal_type,
            "status": _status(existing, recent_count, prev_count, burst_ratio),
            "summary": _summary(label, items),
            "entities": _merged_strings(items, "entities", 12),
            "watch_keywords": _merged_strings(items, "watch_keywords", 12),
            "first_seen_at": first_seen,
            "last_seen_at": last_seen,
            "article_count": article_count,
            "source_count": len(source_names),
            "avg_importance": _avg(items, "importance_score"),
            "avg_evidence_strength": _avg(items, "evidence_strength"),
            "avg_novelty": _avg(items, "novelty_score"),
            "avg_confidence": _avg(items, "confidence"),
            "recent_count_7d": recent_count,
            "previous_count_7d": prev_count,
            "burst_ratio": burst_ratio,
        }
        clusters.append(cluster)
        for item in items:
            links.append({
                "cluster_key": cluster_key,
                "article_id": item["id"],
                "relevance_score": 1.0,
            })

    clusters.sort(key=lambda c: (c["status"] != "bursting", -c["article_count"], c["label"]))
    links.sort(key=lambda link: (link["cluster_key"], link["article_id"]))
    return {"clusters": clusters, "links": links}


def _status(existing: dict[str, Any] | None, recent_count: int, prev_count: int, burst_ratio: float) -> str:
    if burst_ratio >= 2 and recent_count >= 3:
        return "bursting"
    if recent_count > prev_count and recent_count >= 2:
        return "warming"
    if existing is None:
        return "new"
    if recent_count < prev_count:
        return "cooling"
    return "mature"


def _cluster_label(items: list[dict[str, Any]], cluster_key: str) -> str:
    for item in items:
        value = str(item.get("cluster_hint") or "").strip()
        if value:
            return value
    return cluster_key.split(":", 1)[1]


def _summary(label: str, items: list[dict[str, Any]]) -> str:
    signals = [str(item.get("hidden_signal") or item.get("description") or "").strip() for item in items]
    signal = next((s for s in signals if s), "")
    return f"{label}: {signal[:120]}" if signal else label


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _date_range(items: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    dates = [_parse_dt(item.get("publish_time")) for item in items]
    dates = [dt for dt in dates if dt is not None]
    if not dates:
        return None, None
    return min(dates).isoformat(), max(dates).isoformat()


def _avg(items: list[dict[str, Any]], key: str) -> float | None:
    values = [item.get(key) for item in items if isinstance(item.get(key), (int, float))]
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _first_int(items: list[dict[str, Any]], key: str) -> int | None:
    for item in items:
        value = item.get(key)
        if isinstance(value, int):
            return value
    return None


def _first_text(value: Any) -> str:
    if isinstance(value, list) and value:
        return str(value[0]).strip()
    return ""


def _merged_strings(items: list[dict[str, Any]], key: str, limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        values = item.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            text = str(value).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
            if len(out) >= limit:
                return out
    return out
