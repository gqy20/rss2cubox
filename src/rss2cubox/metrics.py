from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def percentile_ms(values: list[int], p: float) -> int:
    if not values:
        return 0
    arr = sorted(values)
    rank = max(1, math.ceil(len(arr) * p)) - 1
    rank = min(rank, len(arr) - 1)
    return int(arr[rank])


class StageMetrics:
    def __init__(self) -> None:
        self._data: dict[str, list[int]] = {}

    def observe(self, stage: str, duration_ms: int) -> None:
        self._data.setdefault(stage, []).append(max(0, int(duration_ms)))

    def total_ms(self, stage: str) -> int:
        return sum(self._data.get(stage, []))

    def p95_ms(self, stage: str) -> int:
        return percentile_ms(self._data.get(stage, []), 0.95)

    def count(self, stage: str) -> int:
        return len(self._data.get(stage, []))

    def snapshot(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for stage in ("fetch", "ai", "push"):
            out[stage] = {
                "count": self.count(stage),
                "total_ms": self.total_ms(stage),
                "p95_ms": self.p95_ms(stage),
            }
        return out


def write_step_summary(summary: dict[str, Any], summary_path: str) -> None:
    if not summary_path:
        return
    lines = [
        "## RSS2Cubox Run Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| feeds_total | {summary.get('feeds_total', 0)} |",
        f"| feeds_invalid | {summary.get('feeds_invalid', 0)} |",
        f"| feeds_circuit_skipped | {summary.get('feeds_circuit_skipped', 0)} |",
        f"| rsshub_routes | {summary.get('rsshub_routes', 0)} |",
        f"| rsshub_fallback_used | {summary.get('rsshub_fallback_used', 0)} |",
        f"| rsshub_instances | {summary.get('rsshub_instances', 0)} |",
        f"| cursor_skipped | {summary.get('cursor_skipped', 0)} |",
        f"| stage_fetch_total_ms | {summary.get('stage_fetch_total_ms', 0)} |",
        f"| stage_fetch_p95_ms | {summary.get('stage_fetch_p95_ms', 0)} |",
        f"| stage_ai_total_ms | {summary.get('stage_ai_total_ms', 0)} |",
        f"| stage_ai_p95_ms | {summary.get('stage_ai_p95_ms', 0)} |",
        f"| stage_push_total_ms | {summary.get('stage_push_total_ms', 0)} |",
        f"| stage_push_p95_ms | {summary.get('stage_push_p95_ms', 0)} |",
        f"| fetched | {summary.get('fetched', 0)} |",
        f"| deduped | {summary.get('deduped', 0)} |",
        f"| run_deduped | {summary.get('run_deduped', 0)} |",
        f"| missing_link | {summary.get('missing_link', 0)} |",
        f"| keyword_filtered | {summary.get('keyword_filtered', 0)} |",
        f"| candidates | {summary.get('candidates', 0)} |",
        f"| candidates_selected | {summary.get('candidates_selected', 0)} |",
        f"| ai_enabled | {summary.get('ai_enabled', False)} |",
        f"| ai_analyzed | {summary.get('ai_analyzed', 0)} |",
        f"| ai_missing | {summary.get('ai_missing', 0)} |",
        f"| ai_kept | {summary.get('ai_kept', 0)} |",
        f"| ai_dropped_keep_false | {summary.get('ai_dropped_keep_false', 0)} |",
        f"| ai_dropped_score | {summary.get('ai_dropped_score', 0)} |",
        f"| push_attempted | {summary.get('push_attempted', 0)} |",
        f"| pushed | {summary.get('pushed', 0)} |",
        f"| push_failed | {summary.get('push_failed', 0)} |",
        f"| state_size | {summary.get('state_size', 0)} |",
        "",
        "### Runtime Context",
        "",
        "```json",
        json.dumps(summary.get("runtime_context", {}), ensure_ascii=False, sort_keys=True),
        "```",
        "",
        "### Config Snapshot",
        "",
        "```json",
        json.dumps(summary.get("config_snapshot", {}), ensure_ascii=False, sort_keys=True),
        "```",
        "",
        "### Per Feed Push Counts",
        "",
        "```json",
        json.dumps(summary.get("per_feed_push_counts", {}), ensure_ascii=False, sort_keys=True),
        "```",
        "",
        "### Per Feed Drop Reasons",
        "",
        "```json",
        json.dumps(summary.get("per_feed_drop_reasons", {}), ensure_ascii=False, sort_keys=True),
        "```",
    ]
    with Path(summary_path).open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def build_run_stats(
    *,
    feeds_total: int,
    rsshub_instances: int,
    ai_enabled: bool,
    runtime_context: dict[str, Any],
    config_snapshot: dict[str, Any],
) -> dict[str, Any]:
    return {
        "feeds_total": feeds_total,
        "feeds_invalid": 0,
        "feeds_circuit_skipped": 0,
        "rsshub_routes": 0,
        "rsshub_fallback_used": 0,
        "rsshub_instances": rsshub_instances,
        "cursor_skipped": 0,
        "stage_fetch_total_ms": 0,
        "stage_fetch_p95_ms": 0,
        "stage_ai_total_ms": 0,
        "stage_ai_p95_ms": 0,
        "stage_push_total_ms": 0,
        "stage_push_p95_ms": 0,
        "fetched": 0,
        "deduped": 0,
        "run_deduped": 0,
        "missing_link": 0,
        "keyword_filtered": 0,
        "candidates": 0,
        "candidates_selected": 0,
        "ai_enabled": ai_enabled,
        "ai_analyzed": 0,
        "ai_missing": 0,
        "ai_kept": 0,
        "ai_dropped_keep_false": 0,
        "ai_dropped_score": 0,
        "push_attempted": 0,
        "pushed": 0,
        "push_failed": 0,
        "state_size": 0,
        "runtime_context": runtime_context,
        "config_snapshot": config_snapshot,
        "per_feed_push_counts": {},
        "per_feed_drop_reasons": {},
    }


def apply_stage_metrics(summary: dict[str, Any], stage_metrics: StageMetrics) -> None:
    summary["stage_fetch_total_ms"] = stage_metrics.total_ms("fetch")
    summary["stage_fetch_p95_ms"] = stage_metrics.p95_ms("fetch")
    summary["stage_ai_total_ms"] = stage_metrics.total_ms("ai")
    summary["stage_ai_p95_ms"] = stage_metrics.p95_ms("ai")
    summary["stage_push_total_ms"] = stage_metrics.total_ms("push")
    summary["stage_push_p95_ms"] = stage_metrics.p95_ms("push")


def build_runtime_context(*, run_id: str, head_sha: str, ref_name: str, event_name: str) -> dict[str, str]:
    return {
        "run_id": run_id,
        "head_sha": head_sha,
        "ref_name": ref_name,
        "event_name": event_name,
    }


def build_config_snapshot(
    *,
    max_items_per_run: int,
    ai_enabled: bool,
    ai_model: str,
    ai_min_score: float,
    ai_timeout_seconds: int,
    ai_retry_attempts: int,
    ai_batch_size: int,
    ai_max_candidates: int,
    feed_connect_timeout_seconds: float,
    feed_read_timeout_seconds: float,
    feed_fetch_concurrency: int,
    rsshub_failure_cooldown_seconds: int,
    feed_failure_cooldown_seconds: int,
    feed_failure_cooldown_max_seconds: int,
    feed_cursor_lookback_hours: int,
) -> dict[str, Any]:
    return {
        "max_items_per_run": max_items_per_run,
        "ai_enabled": ai_enabled,
        "ai_model": ai_model if ai_enabled else "",
        "ai_min_score": ai_min_score,
        "ai_timeout_seconds": ai_timeout_seconds,
        "ai_retry_attempts": ai_retry_attempts,
        "ai_batch_size": ai_batch_size,
        "ai_max_candidates": ai_max_candidates,
        "feed_connect_timeout_seconds": feed_connect_timeout_seconds,
        "feed_read_timeout_seconds": feed_read_timeout_seconds,
        "feed_fetch_concurrency": feed_fetch_concurrency,
        "rsshub_failure_cooldown_seconds": rsshub_failure_cooldown_seconds,
        "feed_failure_cooldown_seconds": feed_failure_cooldown_seconds,
        "feed_failure_cooldown_max_seconds": feed_failure_cooldown_max_seconds,
        "feed_cursor_lookback_hours": feed_cursor_lookback_hours,
    }
