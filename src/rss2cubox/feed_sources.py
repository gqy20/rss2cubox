from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
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

# feeds.txt 解析后的单条订阅源：{"kind": str, "value": str, "label": str, "priority": int}
FeedSpec = dict[str, Any]

# 实例冷却时长的倍率，按失败原因分级，乘在 RSSHUB_FAILURE_COOLDOWN_SECONDS 上。
# 0.0 = 不冷却实例。分级的依据是「这次失败到底能不能说明实例坏了」：
#   route      403/404 是路由需认证/不存在，换实例也没用，冷却只会误伤好实例
#   timeout     ambiguous——实测 /juejin/* 这类抓取型路由在健康实例上也要 19~28s，
#              超时很可能只是路由慢，所以只给很短的冷却，靠 streak 阶梯逐步升级
#   connection 主机层不可达，实例确实坏了，标准冷却
#   ratelimit  429 是我们自己打太狠，必须狠退避
COOLDOWN_REASON_MULTIPLIER: dict[str, float] = {
    "timeout": 0.2,
    "connection": 1.0,
    "ratelimit": 2.0,
    "http5xx": 1.0,
    "http4xx": 1.0,
    "parse": 0.5,
    "preflight": 1.0,
    "other": 1.0,
    "route": 0.0,
}

# FEED_SECTIONS_DISABLE 接受的 token -> 内部 bucket 名
DISABLE_BUCKET_ALIASES: dict[str, str] = {
    "twitter": "twitter_user",
    "twitter_user": "twitter_user",
    "bilibili": "bilibili_user_video",
    "bilibili_user_video": "bilibili_user_video",
    "werss": "werss",
    "default": "default",
}


def classify_fetch_error(exc: BaseException) -> str:
    """把抓取异常归类，用于决定实例冷却策略。见 COOLDOWN_REASON_MULTIPLIER。"""
    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "connection"
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        if status == 429:
            return "ratelimit"
        if status in (403, 404):
            return "route"
        if 500 <= status < 600:
            return "http5xx"
        if 400 <= status < 500:
            return "http4xx"
    if isinstance(exc, ValueError):
        return "parse"
    return "other"


def _resolve_max_candidates(explicit: int | None) -> int:
    """单条路由最多试几个实例，0 = 不限制。"""
    if explicit is not None:
        return max(0, int(explicit))
    raw = os.getenv("RSSHUB_MAX_CANDIDATES", "4").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 4


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
    if text.startswith(("/bilibili/user/video/", "/bilibili/user/video-browser/")):
        return "bilibili_user_video"
    if text.startswith("/twitter/user/"):
        return "twitter_user"
    return "default"


def _route_special_instances(route: str) -> list[str]:
    bucket = _route_bucket(route)
    if bucket == "bilibili_user_video":
        private = _parse_instance_list(os.getenv("RSSHUB_PRIVATE_INSTANCES", "").strip())
        return private + _env_instances("RSSHUB_BILIBILI_INSTANCES", DEFAULT_BILIBILI_SPECIAL_INSTANCES)
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
    max_cooldown_seconds: int = 3600
    fail_until: dict[str, float] = field(default_factory=dict)
    fail_count: dict[str, int] = field(default_factory=dict)
    fail_streak: dict[str, int] = field(default_factory=dict)
    fail_reason: dict[str, str] = field(default_factory=dict)
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
            self.fail_streak.pop(instance, None)
            self.fail_reason.pop(instance, None)
            if instance in self.instances:
                self.instances.remove(instance)
                self.instances.insert(0, instance)

    def mark_failure(self, instance: str, now_ts: float | None = None, *, reason: str = "other") -> int:
        """记录一次失败，返回本次冷却秒数（0 表示不冷却）。

        冷却时长按**连续**失败次数指数退避（fail_streak），封顶 max_cooldown_seconds；
        再乘上 reason 对应的倍率。倍率为 0 的 reason（如 403/404）对实例
        完全无副作用：这类失败反映的是路由问题，不该让好实例背锅。

        fail_count 是累计值，只参与 _score 排序，不影响退避阶梯。
        """
        multiplier = COOLDOWN_REASON_MULTIPLIER.get(reason, 1.0)
        if multiplier <= 0:
            return 0
        now = now_ts or time.time()
        with self._lock:
            self.fail_count[instance] = self.fail_count.get(instance, 0) + 1
            streak = self.fail_streak.get(instance, 0) + 1
            self.fail_streak[instance] = streak
            self.fail_reason[instance] = reason
            backoff = max(0, self.cooldown_seconds) * multiplier * (2 ** (streak - 1))
            ceiling = max(self.cooldown_seconds, self.max_cooldown_seconds)
            cooldown = int(min(backoff, ceiling))
            self.fail_until[instance] = now + cooldown
            if instance in self.instances:
                self.instances.remove(instance)
                self.instances.append(instance)
            return cooldown

    def _score(self, instance: str) -> int:
        return self.success_count.get(instance, 0) - self.fail_count.get(instance, 0)


def _probe_instance(
    base: str,
    *,
    connect_timeout: float,
    read_timeout: float,
) -> tuple[bool, str]:
    """探活单个实例，返回 (是否存活, 失败原因)。

    拿到任意非 5xx 的 HTTP 响应就算活 —— 这里探的是“实例在不在”，
    不是“路由能不能用”，所以 404/403 也算活。
    """
    try:
        response = requests.get(
            f"{base}/",
            timeout=(connect_timeout, read_timeout),
            stream=True,
            headers={"user-agent": "rss2cubox/0.1 (+preflight)"},
        )
    except Exception as exc:  # noqa: BLE001
        return False, classify_fetch_error(exc)
    try:
        status = response.status_code
    finally:
        response.close()
    if status >= 500:
        return False, "http5xx"
    return True, ""


def preflight_instances(
    pool: RSSHubInstancePool,
    *,
    connect_timeout_seconds: float = 3.0,
    read_timeout_seconds: float = 5.0,
    concurrency: int = 10,
    log_event: Any = None,
) -> dict[str, Any]:
    """抓取开始前并发探活所有实例，把死的预先打上冷却。

    目的是消除冷启动惊群：N 个并发路由同时启动时冷却表还是空的，
    于是 N 个请求会一起撞向同一个坏实例（实测失败次数 ≈ 并发数）。
    """
    started = time.perf_counter()
    targets = list(pool.instances)
    alive: list[str] = []
    dead: dict[str, str] = {}
    cooldowns: dict[str, int] = {}

    if targets:
        workers = max(1, min(int(concurrency or 1), len(targets)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _probe_instance,
                    target,
                    connect_timeout=connect_timeout_seconds,
                    read_timeout=read_timeout_seconds,
                ): target
                for target in targets
            }
            for future in as_completed(futures):
                target = futures[future]
                try:
                    is_alive, reason = future.result()
                except Exception as exc:  # noqa: BLE001
                    is_alive, reason = False, classify_fetch_error(exc)
                if is_alive:
                    alive.append(target)
                    continue
                dead[target] = reason or "other"
                cooldowns[target] = pool.mark_failure(target, reason="preflight")

    duration_ms = int((time.perf_counter() - started) * 1000)
    if log_event:
        log_event(
            "WARN" if dead else "INFO",
            "rsshub_preflight_done",
            stage="fetch",
            probed=len(targets),
            alive=len(alive),
            dead=len(dead),
            duration_ms=duration_ms,
            dead_instances={
                _mask_url(k): {"reason": v, "cooldown_seconds": cooldowns.get(k, 0)}
                for k, v in dead.items()
            },
        )
    return {
        "probed": len(targets),
        "alive": alive,
        "dead": dead,
        "cooldown_seconds": cooldowns,
        "duration_ms": duration_ms,
    }


def load_lines(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]


def normalize_feed_kind(kind: str, raw: str) -> str:
    if kind in {"rsshub", "direct", "werss"}:
        return kind
    return "direct" if raw.startswith(("http://", "https://")) else "rsshub"


def split_feed_line(raw: str) -> tuple[int, str, str]:
    """Parse a feed line into (priority, value, label).

    Supported formats:
        5	/feed/path # Label     → (5, "/feed/path", "Label")
        3	/feed/path              → (3, "/feed/path", "")
        /feed/path # Label         → (0, "/feed/path", "Label")
        /feed/path                 → (0, "/feed/path", "")
    """
    text = raw.strip()
    parts = text.split("\t", 1)
    priority = 0
    rest = text
    if len(parts) == 2 and parts[0].strip().lstrip("-").isdigit():
        priority = int(parts[0].strip())
        rest = parts[1].strip()
    if " # " not in rest:
        return priority, rest, ""
    value, label = rest.split(" # ", 1)
    return priority, value.strip(), label.strip()


def split_feed_value_and_label(raw: str) -> tuple[str, str]:
    _, value, label = split_feed_line(raw)
    return value, label


def load_feed_specs(path: Path) -> list[FeedSpec]:
    specs: list[FeedSpec] = []
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
            if lowered in {"[werss]", "werss:"}:
                section = "werss"
                continue
            priority, value, label = split_feed_line(raw)
            if not value:
                continue
            specs.append(
                {
                    "kind": normalize_feed_kind(section, value),
                    "value": value,
                    "label": label,
                    "priority": priority,
                }
            )
    return specs


def spec_bucket(spec: FeedSpec) -> str:
    """把一条 spec 归到可禁用的桶：werss / bilibili_user_video / twitter_user / default。"""
    if str(spec.get("kind", "")) == "werss":
        return "werss"
    return _route_bucket(str(spec.get("value", "")))


def parse_disabled_buckets(raw: str | None) -> set[str]:
    """解析 FEED_SECTIONS_DISABLE，未识别的 token 直接忽略。"""
    out: set[str] = set()
    for part in str(raw or "").split(","):
        token = part.strip().lower()
        if not token:
            continue
        mapped = DISABLE_BUCKET_ALIASES.get(token)
        if mapped:
            out.add(mapped)
    return out


def filter_specs_by_buckets(
    specs: list[FeedSpec],
    disabled_raw: str | set[str] | None,
    *,
    log_event: Any = None,
) -> tuple[list[FeedSpec], dict[str, int]]:
    """按桶过滤掉结构性失效的源，返回 (保留的 specs, 各桶丢弃数)。

    这些源不是“暂时挂了就靠熔断去发现”，而是配置上就拿不到数据
    （比如 twitter 路由无认证实例、werss 服务未部署），每轮都轮一遍
    候选实例纯属烧时间，所以在配置层直接关掉。
    """
    if disabled_raw is None or isinstance(disabled_raw, str):
        disabled = parse_disabled_buckets(disabled_raw)
    else:
        disabled = {str(x) for x in disabled_raw}
    if not disabled:
        return list(specs), {}

    kept: list[FeedSpec] = []
    dropped: Counter[str] = Counter()
    for spec in specs:
        bucket = spec_bucket(spec)
        if bucket in disabled:
            dropped[bucket] += 1
            continue
        kept.append(spec)

    if log_event and dropped:
        log_event(
            "INFO",
            "feed_sections_disabled",
            stage="fetch",
            disabled=sorted(disabled),
            dropped_total=sum(dropped.values()),
            dropped_by_bucket=dict(dropped),
            kept=len(kept),
        )
    return kept, dict(dropped)


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


def resolve_feed_urls(
    feed_kind: str,
    feed_value: str,
    rsshub_pool: RSSHubInstancePool,
    *,
    max_candidates: int | None = None,
) -> list[str]:
    value = feed_value.strip()
    if not value:
        return []
    kind = normalize_feed_kind(feed_kind, value)
    if kind == "direct":
        return [value]
    if kind == "werss":
        if value.startswith(("http://", "https://")):
            return [value]
        base = os.getenv("WERSS_BASE_URL", "").strip().rstrip("/")
        if not base:
            return []
        path = value if value.startswith("/") else f"/{value}"
        return [f"{base}{path}"]

    route = value
    if value.startswith("rsshub://"):
        route = value[len("rsshub://") :]
    if route.startswith(("http://", "https://")):
        return [route]
    if not route.startswith("/"):
        route = f"/{route}"
    ordered = rsshub_pool.ordered_instances()
    special = _route_special_instances(route)
    special_norm: list[str] = []
    merged: list[str] = []
    seen: set[str] = set()
    for base in special:
        value = str(base or "").strip().rstrip("/")
        if value and value not in seen:
            seen.add(value)
            special_norm.append(value)
            merged.append(value)
    for base in ordered:
        value = str(base or "").strip().rstrip("/")
        if not value or value in seen:
            continue
        seen.add(value)
        merged.append(value)
    # 候选上限：实测绝大多数路由在前几个实例就命中，轮满整个池子纯属浪费。
    # 但 bilibili/twitter 的专用实例不被挤掉，否则这些路由直接无实例可用。
    limit = _resolve_max_candidates(max_candidates)
    if limit > 0 and len(merged) > limit:
        merged = merged[: max(limit, len(special_norm))]
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


def fetch_and_check_update(
    url: str,
    *,
    connect_timeout_seconds: float,
    read_timeout_seconds: float,
    cached_last_build_date: str | None,
) -> tuple[Any, bool]:
    """Fetch feed with lastBuildDate optimization.

    Uses stream mode to check lastBuildDate before downloading full content.
    Returns (parsed, was_modified) - parsed is None if feed was not modified.

    Args:
        url: Feed URL to fetch
        connect_timeout_seconds: Connection timeout
        read_timeout_seconds: Read timeout
        cached_last_build_date: Previously cached lastBuildDate, or None to always fetch

    Returns:
        Tuple of (parsed_feed, was_modified) where:
        - parsed_feed: The parsed feed, or None if not modified
        - was_modified: True if feed content changed, False if skipped due to cache
    """
    import re
    import feedparser

    lbd_pattern = re.compile(rb"<lastBuildDate>([^<]+)</lastBuildDate>")

    with requests.get(
        url,
        stream=True,
        timeout=(connect_timeout_seconds, read_timeout_seconds),
        headers={"user-agent": "rss2cubox/0.1 (+github-actions)"},
    ) as response:
        response.raise_for_status()
        content: bytes = b""

        for chunk in response.iter_content(chunk_size=4096):
            content += chunk
            match = lbd_pattern.search(content)
            if match:
                current_lbd = match.group(1).decode("utf-8")
                if cached_last_build_date and current_lbd == cached_last_build_date:
                    return None, False
                for remaining in response.iter_content(chunk_size=65536):
                    content += remaining
                break

        parsed = feedparser.parse(content)
        if getattr(parsed, "bozo", False):
            bozo_exc = getattr(parsed, "bozo_exception", None)
            raise ValueError(f"invalid feed parse: {bozo_exc!r}")

        return parsed, True


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

    # Bilibili: cover is often embedded in the summary/description HTML.
    if "bilibili.com/video/" in url:
        for field in ("summary", "description"):
            val = entry.get(field)
            if isinstance(val, list) and val:
                val = val[0].get("value", "") if isinstance(val[0], dict) else ""
            if isinstance(val, str) and val.strip():
                img_match = re.search(
                    r'<img[^>]+src=["\']([^"\']*hdslb\.com[^"\']*)["\']',
                    val,
                    re.IGNORECASE,
                )
                if img_match:
                    return img_match.group(1)

    return ""


def parse_feed_with_fallback(
    feed_kind: str,
    feed_value: str,
    rsshub_pool: RSSHubInstancePool,
    *,
    fetcher: Any,
    log_event: Any,
) -> tuple[str | None, Any | None, int, list[dict[str, Any]]]:
    """返回 (selected_url, parsed, attempt_index, attempts)

    attempts 是每次候选实例尝试的记录列表，每条包含:
      candidate_url, attempt_index, status, duration_ms, error
    """
    attempts: list[dict[str, Any]] = []
    candidates = resolve_feed_urls(feed_kind, feed_value, rsshub_pool)
    special_instances = set(_route_special_instances(feed_value))
    for idx, candidate_url in enumerate(candidates, start=1):
        instance = candidate_url.split("/", 3)[:3]
        instance_base = "/".join(instance) if len(instance) >= 3 else candidate_url
        if feed_kind == "rsshub" and instance_base not in special_instances and rsshub_pool.should_skip(instance_base):
            log_event(
                "INFO",
                "feed_candidate_skipped_cooldown",
                stage="fetch",
                feed=feed_value,
                candidate=_mask_url(candidate_url),
                attempt=idx,
            )
            attempts.append({
                "candidate_url": candidate_url,
                "attempt_index": idx,
                "status": "skipped",
                "duration_ms": 0,
                "error": None,
            })
            continue
        retry_limit = _candidate_retry_limit(feed_value, instance_base)
        for retry_attempt in range(1, retry_limit + 1):
            start = time.perf_counter()
            try:
                result = fetcher(candidate_url)
                # Support both old interface (returns parsed) and new (returns (parsed, was_modified))
                if isinstance(result, tuple):
                    parsed, was_modified = result
                else:
                    parsed = result
                    was_modified = True
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
                    was_modified=was_modified,
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
                attempts.append({
                    "candidate_url": candidate_url,
                    "attempt_index": idx,
                    "status": "ok",
                    "duration_ms": duration_ms,
                    "error": None,
                })
                return candidate_url, parsed, idx, attempts
            except Exception as exc:  # noqa: BLE001
                duration_ms = int((time.perf_counter() - start) * 1000)
                is_last = retry_attempt >= retry_limit
                reason = classify_fetch_error(exc)
                cooldown_seconds = 0
                if is_last and feed_kind == "rsshub":
                    cooldown_seconds = rsshub_pool.mark_failure(instance_base, reason=reason)
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
                    reason=reason,
                    cooldown_seconds=cooldown_seconds,
                    error=str(exc),
                )
                if is_last:
                    attempts.append({
                        "candidate_url": candidate_url,
                        "attempt_index": idx,
                        "status": "failed",
                        "duration_ms": duration_ms,
                        "reason": reason,
                        "error": str(exc)[:500],
                    })
                if not is_last:
                    time.sleep(min(1.5, 0.35 * retry_attempt))
    return None, None, 0, attempts


def parse_feed_spec(
    spec: FeedSpec,
    analyzed: dict[str, Any],
    feed_cursor: dict[str, Any],
    last_build_cache: dict[str, str] | None,
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
    current_last_build_date: str | None = None

    cursor_raw = str(feed_cursor.get(feed_url, "")).strip()
    cursor_dt = parse_iso_datetime(cursor_raw)
    cutoff_dt = None
    if cursor_dt is not None:
        cutoff_dt = cursor_dt - timedelta(hours=max(0, feed_cursor_lookback_hours))

    log_event("INFO", "feed_fetch_start", stage="fetch", feed=feed_url, kind=feed_kind)
    selected_url, parsed, selected_attempt, attempts = parse_feed_with_fallback(
        feed_kind,
        feed_url,
        rsshub_pool,
        fetcher=fetcher,
        log_event=log_event,
    )

    # Handle the case where fetcher returns (parsed, was_modified)
    was_modified = True
    if isinstance(parsed, tuple):
        parsed, was_modified = parsed

    # If fetcher indicated no modification (304 Not Modified case), return early
    if not was_modified and parsed is None:
        log_event(
            "INFO",
            "feed_not_modified",
            stage="fetch",
            feed=feed_url,
            cached_last_build_date=last_build_cache.get(feed_url) if last_build_cache else None,
        )
        return {
            "ok": True,
            "kind": feed_kind,
            "feed": feed_url,
            "resolved_url": selected_url,
            "selected_attempt": selected_attempt,
            "fetched": 0,
            "candidates": 0,
            "deduped": 0,
            "missing_link": 0,
            "keyword_filtered": 0,
            "cursor_skipped": 0,
            "duration_ms": int((time.perf_counter() - feed_start) * 1000),
            "feed_max_seen_ts": "",
            "not_modified": True,
            "candidate_items": [],
            "attempts": attempts,
        }

    if selected_url is None or parsed is None:
        return {
            "ok": False,
            "kind": feed_kind,
            "feed": feed_url,
            "duration_ms": int((time.perf_counter() - feed_start) * 1000),
            "error": "feed_invalid",
            "attempts": attempts,
        }

    # Extract lastBuildDate from parsed feed
    current_last_build_date = parsed.feed.get("updated") if parsed else None

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
        if eid in analyzed:
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
        publish_time = entry_ts.isoformat() if entry_ts is not None else ""
        source_article_id = str(entry.get("id") or entry.get("guid") or eid).strip() or eid
        if len(description) > 5000:
            description = description[:5000] + "..."
        candidates.append(
            {
                "eid": eid,
                "url": url,
                "title": title,
                "description": description,
                "cover_url": cover_url,
                "publish_time": publish_time,
                "source_feed": feed_url,
                "source_label": source_label,
                "source_article_id": source_article_id,
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
        "last_build_date": current_last_build_date,
        "candidate_items": candidates,
        "attempts": attempts,
    }


def collect_candidates_from_feeds(
    *,
    feed_specs: list[FeedSpec],
    analyzed: dict[str, Any],
    feed_cursor: dict[str, Any],
    last_build_cache: dict[str, str] | None,
    feed_failures: dict[str, Any],
    rsshub_pool: RSSHubInstancePool,
    stats: dict[str, Any],
    stage_metrics: Any,
    feed_fetch_concurrency: int,
    werss_fetch_concurrency: int,
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
    record_stat: Any = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    candidates: list[dict[str, Any]] = []
    pending_specs: list[tuple[int, FeedSpec]] = []
    pending_werss: list[tuple[int, FeedSpec]] = []
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
        if feed_kind == "werss":
            pending_werss.append((idx, spec))
        else:
            pending_specs.append((idx, spec))

    parse_results: dict[int, dict[str, Any]] = {}

    def submit_tasks(executor: ThreadPoolExecutor, specs: list[tuple[int, FeedSpec]]) -> dict[Any, int]:
        return {
            executor.submit(
                parse_feed_spec,
                spec,
                analyzed,
                feed_cursor,
                last_build_cache,
                rsshub_pool,
                feed_cursor_lookback_hours=feed_cursor_lookback_hours,
                include_keywords=include_keywords,
                exclude_keywords=exclude_keywords,
                parse_iso_datetime=parse_iso_datetime,
                parse_entry_timestamp=parse_entry_timestamp,
                stable_id=stable_id,
                passes_filter=passes_filter,
                fetcher=lambda url: fetch_and_check_update(
                    url,
                    connect_timeout_seconds=connect_timeout_seconds,
                    read_timeout_seconds=read_timeout_seconds,
                    cached_last_build_date=last_build_cache.get(spec["value"]) if last_build_cache else None,
                ),
                log_event=log_event,
            ): idx
            for idx, spec in specs
        }

    all_futures: dict[Any, int] = {}

    # WERSS feeds: high concurrency
    if pending_werss:
        werss_workers = min(max(1, werss_fetch_concurrency), max(1, len(pending_werss)))
        with ThreadPoolExecutor(max_workers=werss_workers) as executor:
            all_futures.update(submit_tasks(executor, pending_werss))

    # Non-WERSS feeds: normal concurrency
    if pending_specs:
        normal_workers = min(max(1, feed_fetch_concurrency), max(1, len(pending_specs)))
        with ThreadPoolExecutor(max_workers=normal_workers) as executor:
            all_futures.update(submit_tasks(executor, pending_specs))

    for future in as_completed(all_futures):
        idx = all_futures[future]
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
                "attempts": [],
            }

    for idx in sorted(parse_results):
        result = parse_results[idx]
        feed_url = result["feed"]
        feed_kind = result["kind"]
        attempts = result.get("attempts", [])

        if not result.get("ok", False):
            stats["feeds_invalid"] += 1
            if record_stat:
                for attempt in attempts:
                    record_stat(
                        feed_url=feed_url,
                        candidate_url=attempt.get("candidate_url", ""),
                        attempt_index=attempt.get("attempt_index", 0),
                        status=attempt.get("status", "parse_error"),
                        duration_ms=attempt.get("duration_ms", 0),
                        error_msg=attempt.get("error"),
                    )
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

        if record_stat:
            feed_status = "empty" if result.get("candidates", 0) == 0 else "ok"
            for attempt in attempts:
                is_final = attempt.get("candidate_url") == selected_url and attempt.get("status") == "ok"
                record_stat(
                    feed_url=feed_url,
                    candidate_url=attempt.get("candidate_url", ""),
                    attempt_index=attempt.get("attempt_index", 0),
                    status=feed_status if is_final else attempt.get("status", "failed"),
                    fetched=result.get("fetched", 0) if is_final else 0,
                    candidates=result.get("candidates", 0) if is_final else 0,
                    duration_ms=attempt.get("duration_ms", 0),
                    error_msg=attempt.get("error"),
                )
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

        # Update last_build_cache with current lastBuildDate
        current_lbd = result.get("last_build_date")
        if current_lbd:
            last_build_cache[feed_url] = current_lbd

    # Sort candidates by feed priority (descending) so high-value feeds are processed first
    _feed_priority: dict[str, int] = {spec["value"]: spec.get("priority", 0) for spec in feed_specs}
    candidates.sort(key=lambda c: _feed_priority.get(c.get("source_feed", ""), 0), reverse=True)

    return candidates, last_build_cache


def cap_candidates_per_source(
    candidates: list[dict[str, Any]],
    *,
    max_per_source: int,
    max_total: int,
) -> list[dict[str, Any]]:
    """按源限流后截取，避免单个高产源吃光整轮预算。

    输入必须已按优先级排序：本函数保持顺序遍历，所以高优先级源仍然优先入选，
    只是每个源最多贡献 max_per_source 条。

    为什么需要：候选排序是 priority 降序 + 前缀截取，而 feed 的候选量差异极大
    （实测 openai.com 单个 feed 1193 条、vercel 1578 条）。priority=5 的高产源
    会占满 MAX_ITEMS_PER_RUN，实测一次 1500 篇的运行里 93% 的全文抓取都打在
    openai.com 上——既让整轮产出毫无多样性，又因请求量过大触发对方反爬
    （成功率从隔离测试的 60% 掉到 0%）。

    max_per_source <= 0 表示不限流，退化为原来的前缀截取。
    """
    total = max(1, int(max_total))
    per_source = int(max_per_source)
    if per_source <= 0:
        return candidates[:total]

    counts: Counter[str] = Counter()
    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        source = str(candidate.get("source_feed", "") or "")
        if counts[source] >= per_source:
            continue
        counts[source] += 1
        selected.append(candidate)
        if len(selected) >= total:
            break
    return selected
