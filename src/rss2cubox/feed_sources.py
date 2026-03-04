from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import time

DEFAULT_RSSHUB_INSTANCES = ["https://rsshub.rssforever.com", "https://rsshub.app"]


@dataclass
class RSSHubInstancePool:
    instances: list[str]
    cooldown_seconds: int = 300
    fail_until: dict[str, float] = field(default_factory=dict)
    fail_count: dict[str, int] = field(default_factory=dict)
    success_count: dict[str, int] = field(default_factory=dict)

    def ordered_instances(self, now_ts: float | None = None) -> list[str]:
        now = now_ts or time.time()
        available = [ins for ins in self.instances if self.fail_until.get(ins, 0.0) <= now]
        unavailable = [ins for ins in self.instances if self.fail_until.get(ins, 0.0) > now]
        available.sort(key=self._score, reverse=True)
        unavailable.sort(key=self._score, reverse=True)
        return available + unavailable

    def should_skip(self, instance: str, now_ts: float | None = None) -> bool:
        now = now_ts or time.time()
        return self.fail_until.get(instance, 0.0) > now

    def mark_success(self, instance: str) -> None:
        self.success_count[instance] = self.success_count.get(instance, 0) + 1
        self.fail_until.pop(instance, None)
        if instance in self.instances:
            self.instances.remove(instance)
            self.instances.insert(0, instance)

    def mark_failure(self, instance: str, now_ts: float | None = None) -> None:
        now = now_ts or time.time()
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
            specs.append({"kind": normalize_feed_kind(section, raw), "value": raw})
    return specs


def load_rsshub_instances(path: Path, env_name: str = "RSSHUB_INSTANCES") -> list[str]:
    instances: list[str] = []
    if path.exists():
        instances.extend(load_lines(path))
    if not instances:
        env_value = os.getenv(env_name, "").strip()
        if env_value:
            instances.extend(part.strip() for part in env_value.split(",") if part.strip())
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
    return [f"{base}{route}" for base in rsshub_pool.ordered_instances()]
