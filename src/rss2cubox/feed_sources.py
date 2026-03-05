from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import re
import time
from threading import Lock
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

DEFAULT_RSSHUB_INSTANCES = ["https://rsshub.rssforever.com", "https://rsshub.app"]
DEFAULT_BILIBILI_SPECIAL_INSTANCES = ["https://rss.spriple.org"]
DEFAULT_TWITTER_SPECIAL_INSTANCES: list[str] = []


def _parse_instance_list(raw: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for part in str(raw or "").split(","):
        value = part.strip().rstrip("/")
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


# 私有实例的 host 集合，用于日志打码（从环境变量在模块加载时计算一次）
_PRIVATE_HOSTS: frozenset[str] = frozenset(
    urlparse(inst).netloc
    for inst in _parse_instance_list(os.getenv("RSSHUB_PRIVATE_INSTANCES", "").strip())
    if inst
)


def _mask_url(url: str) -> str:
    """若 URL 的 host 属于私有实例，将 host 替换为 *** 后返回，否则原样返回。"""
    if not _PRIVATE_HOSTS:
        return url
    parsed = urlparse(url)
    if parsed.netloc in _PRIVATE_HOSTS:
        return f"{parsed.scheme}://***{parsed.path}"
    return url


def _env_instances(name: str, default: list[str]) -> list[str]:
    values = _parse_instance_list(os.getenv(name, "").strip())
    if not values:
        return default[:]
    return values


def _route_bucket(route: str) -> str:
    text = str(route or "").strip()
    if text.startswith("/bilibili/user/video/"):
        return "bilibili_user_video"
    if text.startswith("/twitter/user/"):
        return "twitter_user"
    return "default"


def _route_special_instances(route: str) -> list[str]:
    bucket = _route_bucket(route)
    if bucket == "bilibili_user_video":
        return _env_instances("RSSHUB_BILIBILI_INSTANCES", DEFAULT_BILIBILI_SPECIAL_INSTANCES)
    if bucket == "twitter_user":
        return _env_instances("RSSHUB_TWITTER_INSTANCES", DEFAULT_TWITTER_SPECIAL_INSTANCES)
    return []


def _candidate_retry_limit(route: str, instance_base: str) -> int:
    bucket = _route_bucket(route)
    if bucket == "bilibili_user_video":
        special = set(_route_special_instances(route))
        if instance_base in special:
            return max(1, int(os.getenv("RSSHUB_BILIBILI_RETRY_ATTEMPTS", "3")))
    if bucket == "twitter_user":
        special = set(_route_special_instances(route))
        if instance_base in special:
            return max(1, int(os.getenv("RSSHUB_TWITTER_RETRY_ATTEMPTS", "2")))
    return 1


@dataclass
class RSSHubInstancePool:
    instances: list[str]
    cooldown_seconds: int = 300
    fail_until: dict[str, float] = field(default_factory=dict)
    fail_count: dict[str, int] = field(default_factory=dict)
    success_count: dict[str, int] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def ordered_instances(self, now_ts: float | None = None) -> list[str]:
        now = now_ts or time.time()
        with self._lock:
            available = [ins for ins in self.instances if self.fail_until.get(ins, 0.0) <= now]
            unavailable = [ins for ins in self.instances if self.fail_until.get(ins, 0.0) > now]
            available.sort(key=self._score, reverse=True)
            unavailable.sort(key=self._score, reverse=True)
            return available + unavailable

    def should_skip(self, instance: str, now_ts: float | None = None) -> bool:
        now = now_ts or time.time()
        with self._lock:
            return self.fail_until.get(instance, 0.0) > now

    def mark_success(self, instance: str) -> None:
        with self._lock:
            self.success_count[instance] = self.success_count.get(instance, 0) + 1
            self.fail_until.pop(instance, None)
            if instance in self.instances:
                self.instances.remove(instance)
                self.instances.insert(0, instance)

    def mark_failure(self, instance: str, now_ts: float | None = None) -> None:
        now = now_ts or time.time()
        with self._lock:
            self.fail_count[instance] = self.fail_count.get(instance, 0) + 1
            self.fail_until[instance] = now + max(0, self.cooldown_seconds)
            if instance in self.instances:
                self.instances.remove(instance)
                self.instances.append(instance)

    def _score(self, instance: str) -> int:
        return self.success_count.get(instance, 0) - self.fail_count.get(instance, 0)


def load_lines(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]


def normalize_feed_kind(kind: str, raw: str) -> str:
    if kind in {"rsshub", "direct"}:
        return kind
    return "direct" if raw.startswith(("http://", "https://")) else "rsshub"


def split_feed_value_and_label(raw: str) -> tuple[str, str]:
    text = raw.strip()
    if " # " not in text:
        return text, ""
    value, label = text.split(" # ", 1)
    return value.strip(), label.strip()


def load_feed_specs(path: Path) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    section = "auto"
    with path.open("r", encoding="utf-8") as f:
        for ln in f:
            raw = ln.strip()
            if not raw or raw.startswith("#"):
                continue
            lowered = raw.lower()
            if lowered in {"[rsshub]", "rsshub:"}:
                section = "rsshub"
                continue
            if lowered in {"[direct]", "direct:"}:
                section = "direct"
                continue
            value, label = split_feed_value_and_label(raw)
            if not value:
                continue
            specs.append(
                {
                    "kind": normalize_feed_kind(section, value),
                    "value": value,
                    "label": label,
                }
            )
    return specs


def load_rsshub_instances(path: Path, env_name: str = "RSSHUB_INSTANCES") -> list[str]:
    instances: list[str] = []
    # Private instances from secrets are preferred and always loaded first.
    instances.extend(_parse_instance_list(os.getenv("RSSHUB_PRIVATE_INSTANCES", "").strip()))
    if path.exists():
        instances.extend(load_lines(path))
    env_value = os.getenv(env_name, "").strip()
    if env_value:
        instances.extend(_parse_instance_list(env_value))
    if not instances:
        instances = DEFAULT_RSSHUB_INSTANCES[:]

    normalized: list[str] = []
    seen: set[str] = set()
    for instance in instances:
        v = instance.strip().rstrip("/")
        if not v or v in seen:
            continue
        seen.add(v)
        normalized.append(v)
    return normalized


def resolve_feed_urls(feed_kind: str, feed_value: str, rsshub_pool: RSSHubInstancePool) -> list[str]:
    value = feed_value.strip()
    if not value:
        return []
    kind = normalize_feed_kind(feed_kind, value)
    if kind == "direct":
        return [value]

    route = value
    if value.startswith("rsshub://"):
        route = value[len("rsshub://") :]
    if route.startswith(("http://", "https://")):
        return [route]
    if not route.startswith("/"):
        route = f"/{route}"
    ordered = rsshub_pool.ordered_instances()
    special = _route_special_instances(route)
    merged: list[str] = []
    seen: set[str] = set()
    for base in special + ordered:
        value = str(base or "").strip().rstrip("/")
        if not value or value in seen:
            continue
        seen.add(value)
        merged.append(value)
    return [f"{base}{route}" for base in merged]


def fetch_and_parse_feed(
    url: str,
    *,
    connect_timeout_seconds: float,
    read_timeout_seconds: float,
) -> Any:
    response = requests.get(
        url,
        timeout=(connect_timeout_seconds, read_timeout_seconds),
        headers={"user-agent": "rss2cubox/0.1 (+github-actions)"},
    )
    response.raise_for_status()
    import feedparser

    parsed = feedparser.parse(response.content)
    if getattr(parsed, "bozo", False):
        bozo_exc = getattr(parsed, "bozo_exception", None)
        raise ValueError(f"invalid feed parse: {bozo_exc!r}")
    return parsed


def _extract_youtube_video_id(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    host = parsed.netloc.lower()
    path = parsed.path or ""

    if "youtu.be" in host:
        return path.strip("/").split("/")[0] if path.strip("/") else ""
    if "youtube.com" in host:
        if path == "/watch":
            qs = parse_qs(parsed.query)
            return (qs.get("v", [""])[0] or "").strip()
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
            return parts[1].strip()
    return ""


def _pick_url(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        return text if text.startswith(("http://", "https://")) else ""
    if isinstance(value, dict):
        for key in ("url", "href", "src", "value"):
            text = _pick_url(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, list):
        for item in value:
            text = _pick_url(item)
            if text:
                return text
    return ""


def extract_cover_url(entry: Any, url: str) -> str:
    # Prefer explicit image fields from feed entries.
    field_candidates = [
        entry.get("media_thumbnail"),
        entry.get("media_content"),
        entry.get("itunes_image"),
        entry.get("image"),
        entry.get("cover"),
        entry.get("thumbnail"),
    ]
    for field in field_candidates:
        candidate = _pick_url(field)
        if candidate:
            return candidate

    for link in entry.get("links", []) or []:
        if not isinstance(link, dict):
            continue
        href = _pick_url(link.get("href"))
        rel = str(link.get("rel", "")).lower()
        link_type = str(link.get("type", "")).lower()
        if href and (rel == "enclosure" or link_type.startswith("image/")):
            return href

    for enclosure in entry.get("enclosures", []) or []:
        href = _pick_url(enclosure.get("href") if isinstance(enclosure, dict) else enclosure)
        if href:
            return href

    # URL-based fallback for YouTube.
    yt_video_id = _extract_youtube_video_id(url)
    if yt_video_id and re.fullmatch(r"[A-Za-z0-9_-]{6,20}", yt_video_id):
        return f"https://i.ytimg.com/vi/{yt_video_id}/hqdefault.jpg"

    return ""


def parse_feed_with_fallback(
    feed_kind: str,
    feed_value: str,
    rsshub_pool: RSSHubInstancePool,
    *,
    fetcher: Any,
    log_event: Any,
) -> tuple[str | None, Any | None, int]:
    candidates = resolve_feed_urls(feed_kind, feed_value, rsshub_pool)
    for idx, candidate_url in enumerate(candidates, start=1):
        instance = candidate_url.split("/", 3)[:3]
        instance_base = "/".join(instance) if len(instance) >= 3 else candidate_url
        if feed_kind == "rsshub" and rsshub_pool.should_skip(instance_base):
            log_event(
                "INFO",
                "feed_candidate_skipped_cooldown",
                stage="fetch",
                feed=feed_value,
                candidate=_mask_url(candidate_url),
                attempt=idx,
            )
            continue
        retry_limit = _candidate_retry_limit(feed_value, instance_base)
        for retry_attempt in range(1, retry_limit + 1):
            start = time.perf_counter()
            try:
                parsed = fetcher(candidate_url)
                if feed_kind == "rsshub":
                    rsshub_pool.mark_success(instance_base)
                duration_ms = int((time.perf_counter() - start) * 1000)
                log_event(
                    "INFO",
                    "feed_candidate_success",
                    stage="fetch",
                    feed=feed_value,
                    candidate=_mask_url(candidate_url),
                    attempt=idx,
                    retry_attempt=retry_attempt,
                    retry_limit=retry_limit,
                    duration_ms=duration_ms,
                )
                if idx > 1:
                    log_event(
                        "WARN",
                        "feed_fallback_used",
                        stage="fetch",
                        feed=feed_value,
                        selected=_mask_url(candidate_url),
                        attempt=idx,
                    )
                return candidate_url, parsed, idx
            except Exception as exc:  # noqa: BLE001
                duration_ms = int((time.perf_counter() - start) * 1000)
                is_last = retry_attempt >= retry_limit
                if is_last and feed_kind == "rsshub":
                    rsshub_pool.mark_failure(instance_base)
                log_event(
                    "WARN",
                    "feed_candidate_failed",
                    stage="fetch",
                    feed=feed_value,
                    candidate=_mask_url(candidate_url),
                    attempt=idx,
                    retry_attempt=retry_attempt,
                    retry_limit=retry_limit,
                    duration_ms=duration_ms,
                    error=str(exc),
                )
                if not is_last:
                    time.sleep(min(1.5, 0.35 * retry_attempt))
    return None, None, 0


def parse_feed_spec(
    spec: dict[str, str],
    sent: dict[str, Any],
    feed_cursor: dict[str, Any],
    rsshub_pool: RSSHubInstancePool,
    *,
    feed_cursor_lookback_hours: int,
    include_keywords: list[str],
    exclude_keywords: list[str],
    parse_iso_datetime: Any,
    parse_entry_timestamp: Any,
    stable_id: Any,
    passes_filter: Any,
    fetcher: Any,
    log_event: Any,
) -> dict[str, Any]:
    feed_kind = spec["kind"]
    feed_url = spec["value"]
    source_label = str(spec.get("label", "")).strip()
    feed_seen = 0
    feed_candidates = 0
    feed_deduped = 0
    feed_missing_link = 0
    feed_keyword_filtered = 0
    cursor_skipped = 0
    feed_start = time.perf_counter()
    feed_max_seen_ts: datetime | None = None

    cursor_raw = str(feed_cursor.get(feed_url, "")).strip()
    cursor_dt = parse_iso_datetime(cursor_raw)
    cutoff_dt = None
    if cursor_dt is not None:
        cutoff_dt = cursor_dt - timedelta(hours=max(0, feed_cursor_lookback_hours))

    log_event("INFO", "feed_fetch_start", stage="fetch", feed=feed_url, kind=feed_kind)
    selected_url, parsed, selected_attempt = parse_feed_with_fallback(
        feed_kind,
        feed_url,
        rsshub_pool,
        fetcher=fetcher,
        log_event=log_event,
    )
    if selected_url is None or parsed is None:
        return {
            "ok": False,
            "kind": feed_kind,
            "feed": feed_url,
            "duration_ms": int((time.perf_counter() - feed_start) * 1000),
            "error": "feed_invalid",
        }

    candidates: list[dict[str, Any]] = []
    for entry in parsed.entries:
        feed_seen += 1
        entry_ts = parse_entry_timestamp(entry)
        if entry_ts is not None and (feed_max_seen_ts is None or entry_ts > feed_max_seen_ts):
            feed_max_seen_ts = entry_ts
        if cutoff_dt is not None and entry_ts is not None and entry_ts < cutoff_dt:
            cursor_skipped += 1
            continue

        eid = stable_id(entry)
        if eid in sent:
            feed_deduped += 1
            continue
        if not entry.get("link"):
            feed_missing_link += 1
            continue
        if not passes_filter(entry, include_keywords, exclude_keywords):
            feed_keyword_filtered += 1
            continue

        url = entry["link"]
        title = entry.get("title", "") or ""
        description = (entry.get("summary", "") or "").strip()
        cover_url = extract_cover_url(entry, url)
        if len(description) > 5000:
            description = description[:5000] + "..."
        candidates.append(
            {
                "eid": eid,
                "url": url,
                "title": title,
                "description": description,
                "cover_url": cover_url,
                "source_feed": feed_url,
                "source_label": source_label,
            }
        )
        feed_candidates += 1

    feed_duration_ms = int((time.perf_counter() - feed_start) * 1000)
    return {
        "ok": True,
        "kind": feed_kind,
        "feed": feed_url,
        "resolved_url": selected_url,
        "selected_attempt": selected_attempt,
        "fetched": feed_seen,
        "candidates": feed_candidates,
        "deduped": feed_deduped,
        "missing_link": feed_missing_link,
        "keyword_filtered": feed_keyword_filtered,
        "cursor_skipped": cursor_skipped,
        "duration_ms": feed_duration_ms,
        "feed_max_seen_ts": feed_max_seen_ts.isoformat() if feed_max_seen_ts else "",
        "candidate_items": candidates,
    }


def collect_candidates_from_feeds(
    *,
    feed_specs: list[dict[str, str]],
    sent: dict[str, Any],
    feed_cursor: dict[str, Any],
    feed_failures: dict[str, Any],
    rsshub_pool: RSSHubInstancePool,
    stats: dict[str, Any],
    stage_metrics: Any,
    feed_fetch_concurrency: int,
    feed_cursor_lookback_hours: int,
    include_keywords: list[str],
    exclude_keywords: list[str],
    connect_timeout_seconds: float,
    read_timeout_seconds: float,
    feed_failure_cooldown_seconds: int,
    feed_failure_cooldown_max_seconds: int,
    parse_iso_datetime: Any,
    parse_entry_timestamp: Any,
    stable_id: Any,
    passes_filter: Any,
    feed_is_circuit_open: Any,
    feed_failure_backoff_seconds: Any,
    log_event: Any,
    now_utc: datetime,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    pending_specs: list[tuple[int, dict[str, str]]] = []
    for idx, spec in enumerate(feed_specs):
        feed_kind = spec["kind"]
        feed_url = spec["value"]
        if feed_kind == "rsshub":
            stats["rsshub_routes"] += 1

        failure_state = feed_failures.get(feed_url, {})
        is_open, remaining_seconds = feed_is_circuit_open(failure_state, now_utc)
        if is_open:
            stats["feeds_circuit_skipped"] += 1
            log_event(
                "WARN",
                "feed_skipped_circuit_open",
                stage="fetch",
                feed=feed_url,
                kind=feed_kind,
                remaining_seconds=remaining_seconds,
                failure_count=int(failure_state.get("count", 0)),
            )
            continue
        pending_specs.append((idx, spec))

    parse_results: dict[int, dict[str, Any]] = {}
    max_workers = min(max(1, feed_fetch_concurrency), max(1, len(pending_specs)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                parse_feed_spec,
                spec,
                sent,
                feed_cursor,
                rsshub_pool,
                feed_cursor_lookback_hours=feed_cursor_lookback_hours,
                include_keywords=include_keywords,
                exclude_keywords=exclude_keywords,
                parse_iso_datetime=parse_iso_datetime,
                parse_entry_timestamp=parse_entry_timestamp,
                stable_id=stable_id,
                passes_filter=passes_filter,
                fetcher=lambda url: fetch_and_parse_feed(
                    url,
                    connect_timeout_seconds=connect_timeout_seconds,
                    read_timeout_seconds=read_timeout_seconds,
                ),
                log_event=log_event,
            ): idx
            for idx, spec in pending_specs
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            spec = feed_specs[idx]
            feed_url = spec["value"]
            feed_kind = spec["kind"]
            try:
                parse_results[idx] = future.result()
            except Exception as exc:  # noqa: BLE001
                parse_results[idx] = {
                    "ok": False,
                    "kind": feed_kind,
                    "feed": feed_url,
                    "duration_ms": 0,
                    "error": str(exc),
                }

    for idx in sorted(parse_results):
        result = parse_results[idx]
        feed_url = result["feed"]
        feed_kind = result["kind"]
        if not result.get("ok", False):
            stats["feeds_invalid"] += 1
            previous_count = int(feed_failures.get(feed_url, {}).get("count", 0))
            failure_count = previous_count + 1
            cooldown_seconds = feed_failure_backoff_seconds(
                failure_count,
                feed_failure_cooldown_seconds,
                feed_failure_cooldown_max_seconds,
            )
            feed_failures[feed_url] = {
                "count": failure_count,
                "cooldown_until": (datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)).isoformat(),
                "last_error": str(result.get("error", "feed_invalid")),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            log_event(
                "WARN",
                "feed_invalid",
                stage="fetch",
                feed=feed_url,
                kind=feed_kind,
                failure_count=failure_count,
                cooldown_seconds=cooldown_seconds,
            )
            continue

        selected_url = result["resolved_url"]
        selected_attempt = int(result.get("selected_attempt", 1))
        resolved_from_pool = selected_url != feed_url and feed_kind == "rsshub"
        if selected_attempt > 1:
            stats["rsshub_fallback_used"] += 1
        if resolved_from_pool:
            log_event(
                "INFO",
                "feed_resolved",
                stage="fetch",
                feed=feed_url,
                kind=feed_kind,
                resolved_url=selected_url,
            )
        feed_failures.pop(feed_url, None)

        stats["fetched"] += int(result.get("fetched", 0))
        stats["deduped"] += int(result.get("deduped", 0))
        stats["missing_link"] += int(result.get("missing_link", 0))
        stats["keyword_filtered"] += int(result.get("keyword_filtered", 0))
        stats["cursor_skipped"] += int(result.get("cursor_skipped", 0))
        stage_metrics.observe("fetch", int(result.get("duration_ms", 0)))
        candidates.extend(result.get("candidate_items", []))

        log_event(
            "INFO",
            "feed_processed",
            stage="fetch",
            feed=feed_url,
            kind=feed_kind,
            resolved_url=selected_url,
            fetched=result.get("fetched", 0),
            candidates=result.get("candidates", 0),
            duration_ms=result.get("duration_ms", 0),
        )

        feed_max_seen_ts = parse_iso_datetime(str(result.get("feed_max_seen_ts", "")))
        if feed_max_seen_ts is not None:
            prev_dt = parse_iso_datetime(str(feed_cursor.get(feed_url, "")))
            if prev_dt is None or feed_max_seen_ts > prev_dt:
                feed_cursor[feed_url] = feed_max_seen_ts.isoformat()

    return candidates
