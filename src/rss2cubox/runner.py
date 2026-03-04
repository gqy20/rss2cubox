#!/usr/bin/env python3
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from rss2cubox import feed_sources, sync_pipeline
from rss2cubox.ai_pipeline import (
    ai_analysis_enabled,
    analyze_candidates_with_ai,
)
from rss2cubox.enrich_agent import run_enrich_analysis
from rss2cubox.global_agent import run_global_analysis
from rss2cubox.feed_sources import RSSHubInstancePool
from rss2cubox.metrics import (
    StageMetrics,
    apply_stage_metrics,
    build_config_snapshot,
    build_run_stats,
    build_runtime_context,
    write_step_summary,
)

FEEDS_FILE = Path(os.getenv("FEEDS_FILE", "feeds.txt"))
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
RSSHUB_INSTANCES_FILE = Path(os.getenv("RSSHUB_INSTANCES_FILE", "rsshub_instances.txt"))
RUN_EVENTS_FILE = Path(os.getenv("RUN_EVENTS_FILE", "run_events.jsonl"))

CUBOX_API_URL = os.getenv("CUBOX_API_URL")
CUBOX_FOLDER = os.getenv("CUBOX_FOLDER", "RSS Inbox")
KEYWORDS_INCLUDE = [k.strip() for k in os.getenv("KEYWORDS_INCLUDE", "").split(",") if k.strip()]
KEYWORDS_EXCLUDE = [k.strip() for k in os.getenv("KEYWORDS_EXCLUDE", "").split(",") if k.strip()]
MAX_ITEMS_PER_RUN = int(os.getenv("MAX_ITEMS_PER_RUN", "20"))

ANTHROPIC_AUTH_TOKEN = os.getenv("ANTHROPIC_AUTH_TOKEN", "").strip()
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "").strip()
AI_MIN_SCORE = sync_pipeline.env_float("AI_MIN_SCORE", 0.6)
AI_TIMEOUT_SECONDS = sync_pipeline.env_int("AI_TIMEOUT_SECONDS", 90)
AI_RETRY_ATTEMPTS = sync_pipeline.env_int("AI_RETRY_ATTEMPTS", 3)
AI_RETRY_BACKOFF_SECONDS = sync_pipeline.env_float("AI_RETRY_BACKOFF_SECONDS", 1.5)
AI_BATCH_SIZE = sync_pipeline.env_int("AI_BATCH_SIZE", 5)
AI_MAX_WORKERS = sync_pipeline.env_int("AI_MAX_WORKERS", 10)
AI_MAX_CANDIDATES = sync_pipeline.env_int("AI_MAX_CANDIDATES", max(MAX_ITEMS_PER_RUN * 2, 1))
FEED_CONNECT_TIMEOUT_SECONDS = sync_pipeline.env_float("FEED_CONNECT_TIMEOUT_SECONDS", 5.0)
FEED_READ_TIMEOUT_SECONDS = sync_pipeline.env_float("FEED_READ_TIMEOUT_SECONDS", 10.0)
FEED_FETCH_CONCURRENCY = max(1, sync_pipeline.env_int("FEED_FETCH_CONCURRENCY", 10))
RSSHUB_FAILURE_COOLDOWN_SECONDS = sync_pipeline.env_int("RSSHUB_FAILURE_COOLDOWN_SECONDS", 300)
FEED_CURSOR_LOOKBACK_HOURS = sync_pipeline.env_int("FEED_CURSOR_LOOKBACK_HOURS", 24)
FEED_FAILURE_COOLDOWN_SECONDS = max(1, sync_pipeline.env_int("FEED_FAILURE_COOLDOWN_SECONDS", 60))
FEED_FAILURE_COOLDOWN_MAX_SECONDS = max(
    FEED_FAILURE_COOLDOWN_SECONDS,
    sync_pipeline.env_int("FEED_FAILURE_COOLDOWN_MAX_SECONDS", 1800),
)


def log_event(level: str, event: str, **fields: Any) -> None:
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "event": event,
    }
    payload.update(fields)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str), flush=True)


def main() -> None:
    feed_specs = feed_sources.load_feed_specs(FEEDS_FILE)
    rsshub_instances = feed_sources.load_rsshub_instances(RSSHUB_INSTANCES_FILE)
    rsshub_pool = RSSHubInstancePool(
        instances=rsshub_instances,
        cooldown_seconds=RSSHUB_FAILURE_COOLDOWN_SECONDS,
    )
    stage_metrics = StageMetrics()
    state = sync_pipeline.load_state(STATE_FILE)
    sent = state.get("sent", {})
    ai = state.get("ai", {})
    feed_cursor = state.get("feed_cursor", {})
    feed_failures = state.get("feed_failures", {})
    if not isinstance(feed_failures, dict):
        feed_failures = {}

    now = datetime.now(timezone.utc).isoformat()
    now_utc = datetime.now(timezone.utc)
    enabled = ai_analysis_enabled(ANTHROPIC_AUTH_TOKEN, ANTHROPIC_MODEL)
    runtime_context = build_runtime_context(
        run_id=os.getenv("GITHUB_RUN_ID", ""),
        head_sha=os.getenv("GITHUB_SHA", ""),
        ref_name=os.getenv("GITHUB_REF_NAME", ""),
        event_name=os.getenv("GITHUB_EVENT_NAME", ""),
    )
    config_snapshot = build_config_snapshot(
        max_items_per_run=MAX_ITEMS_PER_RUN,
        ai_enabled=enabled,
        ai_model=ANTHROPIC_MODEL,
        ai_min_score=AI_MIN_SCORE,
        ai_timeout_seconds=AI_TIMEOUT_SECONDS,
        ai_retry_attempts=AI_RETRY_ATTEMPTS,
        ai_batch_size=AI_BATCH_SIZE,
        ai_max_candidates=AI_MAX_CANDIDATES,
        feed_connect_timeout_seconds=FEED_CONNECT_TIMEOUT_SECONDS,
        feed_read_timeout_seconds=FEED_READ_TIMEOUT_SECONDS,
        feed_fetch_concurrency=FEED_FETCH_CONCURRENCY,
        rsshub_failure_cooldown_seconds=RSSHUB_FAILURE_COOLDOWN_SECONDS,
        feed_failure_cooldown_seconds=FEED_FAILURE_COOLDOWN_SECONDS,
        feed_failure_cooldown_max_seconds=FEED_FAILURE_COOLDOWN_MAX_SECONDS,
        feed_cursor_lookback_hours=FEED_CURSOR_LOOKBACK_HOURS,
    )
    stats = build_run_stats(
        feeds_total=len(feed_specs),
        rsshub_instances=len(rsshub_instances),
        ai_enabled=enabled,
        runtime_context=runtime_context,
        config_snapshot=config_snapshot,
    )
    run_events: list[dict[str, Any]] = []
    log_event(
        "INFO",
        "run_start",
        stage="start",
        feeds_total=stats["feeds_total"],
        max_items_per_run=MAX_ITEMS_PER_RUN,
        rsshub_instances=stats["rsshub_instances"],
        ai_enabled=stats["ai_enabled"],
        ai_model=ANTHROPIC_MODEL if stats["ai_enabled"] else "",
        feed_fetch_concurrency=FEED_FETCH_CONCURRENCY,
    )

    candidates = feed_sources.collect_candidates_from_feeds(
        feed_specs=feed_specs,
        sent=sent,
        feed_cursor=feed_cursor,
        feed_failures=feed_failures,
        rsshub_pool=rsshub_pool,
        stats=stats,
        stage_metrics=stage_metrics,
        feed_fetch_concurrency=FEED_FETCH_CONCURRENCY,
        feed_cursor_lookback_hours=FEED_CURSOR_LOOKBACK_HOURS,
        include_keywords=KEYWORDS_INCLUDE,
        exclude_keywords=KEYWORDS_EXCLUDE,
        connect_timeout_seconds=FEED_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds=FEED_READ_TIMEOUT_SECONDS,
        feed_failure_cooldown_seconds=FEED_FAILURE_COOLDOWN_SECONDS,
        feed_failure_cooldown_max_seconds=FEED_FAILURE_COOLDOWN_MAX_SECONDS,
        parse_iso_datetime=sync_pipeline.parse_iso_datetime,
        parse_entry_timestamp=sync_pipeline.parse_entry_timestamp,
        stable_id=sync_pipeline.stable_id,
        passes_filter=sync_pipeline.passes_filter,
        feed_is_circuit_open=sync_pipeline.feed_is_circuit_open,
        feed_failure_backoff_seconds=sync_pipeline.feed_failure_backoff_seconds,
        log_event=log_event,
        now_utc=now_utc,
    )

    candidates, run_deduped = sync_pipeline.dedupe_run_candidates(candidates, stats["per_feed_drop_reasons"])
    stats["run_deduped"] += run_deduped
    stats["candidates"] = len(candidates)

    candidates_for_run = candidates[: max(1, AI_MAX_CANDIDATES)]
    stats["candidates_selected"] = len(candidates_for_run)
    if len(candidates_for_run) < len(candidates):
        log_event(
            "INFO",
            "candidates_limited",
            stage="pre_push",
            selected=len(candidates_for_run),
            total=len(candidates),
        )

    analyses = analyze_candidates_with_ai(
        candidates=candidates_for_run,
        stage_metrics=stage_metrics,
        auth_token=ANTHROPIC_AUTH_TOKEN,
        base_url=ANTHROPIC_BASE_URL,
        model=ANTHROPIC_MODEL,
        timeout_seconds=AI_TIMEOUT_SECONDS,
        retry_attempts=AI_RETRY_ATTEMPTS,
        retry_backoff_seconds=AI_RETRY_BACKOFF_SECONDS,
        batch_size=AI_BATCH_SIZE,
        max_workers=AI_MAX_WORKERS,
        log_event=log_event,
    )
    stats["ai_analyzed"] = len(analyses)
    ai_enabled = stats["ai_enabled"]
    if ai_enabled and analyses:
        missing = sum(1 for item in candidates_for_run if item["eid"] not in analyses)
        stats["ai_missing"] = missing
        if missing:
            log_event("WARN", "ai_missing_results", stage="ai_analyze", missing=missing)
        candidates_for_run = sync_pipeline.reorder_candidates_by_ai_score(
            candidates_for_run,
            analyses,
            ai_enabled=ai_enabled,
            ai_min_score=AI_MIN_SCORE,
        )
        log_event(
            "INFO",
            "candidates_reordered_by_ai_score",
            stage="ai_decision",
            candidates=len(candidates_for_run),
        )
        run_enrich_analysis(
            candidates=candidates_for_run,
            analyses=analyses,
            ai_min_score=AI_MIN_SCORE,
            log_event=log_event,
        )

    sync_pipeline.process_candidates_for_push(
        candidates_for_run=candidates_for_run,
        analyses=analyses,
        stats=stats,
        sent=sent,
        ai_state=ai,
        now_iso=now,
        max_items_per_run=MAX_ITEMS_PER_RUN,
        ai_enabled=ai_enabled,
        ai_min_score=AI_MIN_SCORE,
        ai_model=ANTHROPIC_MODEL,
        cubox_api_url=CUBOX_API_URL,
        cubox_folder=CUBOX_FOLDER,
        request_post=requests.post,
        stage_metrics=stage_metrics,
        log_event=log_event,
        event_sink=run_events,
    )
    for event in run_events:
        event.setdefault("run_id", runtime_context.get("run_id", ""))
        event.setdefault("head_sha", runtime_context.get("head_sha", ""))
        event.setdefault("ref_name", runtime_context.get("ref_name", ""))
        event.setdefault("event_name", runtime_context.get("event_name", ""))
    sync_pipeline.save_jsonl(RUN_EVENTS_FILE, run_events)

    # 全局 Agent 深度分析（如失败不影响主流程）
    try:
        run_global_analysis(analyses=analyses, candidates=candidates_for_run)
    except Exception as e:
        log_event("WARN", "global_agent_failed", stage="global_agent", error=str(e))

    state["sent"] = sent
    state["ai"] = ai
    state["feed_cursor"] = feed_cursor
    state["feed_failures"] = feed_failures
    sync_pipeline.save_state(STATE_FILE, state)
    apply_stage_metrics(stats, stage_metrics)
    stats["state_size"] = len(sent)
    write_step_summary(stats, os.getenv("GITHUB_STEP_SUMMARY", "").strip())
    log_event("INFO", "run_summary", stage="summary", **stats)
    print(f"Done. Pushed {stats['pushed']} items. State size={len(sent)}", flush=True)


if __name__ == "__main__":
    main()
