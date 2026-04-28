#!/usr/bin/env python3
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_local_env_file(env_file: Path = Path(".env")) -> None:
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, value.strip())


_load_local_env_file()

import requests

from rss2cubox import feed_sources, sync_pipeline
from rss2cubox import enrich_agent
from rss2cubox.db_client import save_articles
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
RSSHUB_INSTANCES_FILE = Path(os.getenv("RSSHUB_INSTANCES_FILE", "rsshub_instances.txt"))

IC_API_URL = os.getenv("IC_API_URL", "").strip()
IC_SOURCE_TYPE = os.getenv("IC_SOURCE_TYPE", "gqy").strip() or "gqy"
KEYWORDS_INCLUDE = [k.strip() for k in os.getenv("KEYWORDS_INCLUDE", "").split(",") if k.strip()]
KEYWORDS_EXCLUDE = [k.strip() for k in os.getenv("KEYWORDS_EXCLUDE", "").split(",") if k.strip()]
MAX_ITEMS_PER_RUN = int(os.getenv("MAX_ITEMS_PER_RUN", "500"))

ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "").strip()
AI_MAX_CANDIDATES = sync_pipeline.env_int("AI_MAX_CANDIDATES", 500)
FEED_CONNECT_TIMEOUT_SECONDS = sync_pipeline.env_float("FEED_CONNECT_TIMEOUT_SECONDS", 5.0)
FEED_READ_TIMEOUT_SECONDS = sync_pipeline.env_float("FEED_READ_TIMEOUT_SECONDS", 30.0)
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
    processed, feed_cursor = sync_pipeline.load_ic_state(
        api_url=IC_API_URL,
        source_type=IC_SOURCE_TYPE,
        request_get=requests.get,
    )
    feed_failures: dict[str, Any] = {}

    now = datetime.now(timezone.utc).isoformat()
    now_utc = datetime.now(timezone.utc)
    enabled = enrich_agent.ENRICH_AGENT_ENABLED
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
        analyzed=processed,
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

    analyses = enrich_agent.analyze_candidates_with_agent(
        candidates=candidates_for_run,
        log_event=log_event,
    )
    stats["ai_analyzed"] = len(candidates_for_run)
    ai_enabled = stats["ai_enabled"]
    if ai_enabled and analyses:
        missing = sum(1 for item in candidates_for_run if item["eid"] not in analyses)
        stats["ai_missing"] = missing
        if missing:
            log_event("WARN", "ai_missing_results", stage="agent", missing=missing)

    article_records: list[dict[str, Any]] = []
    for item in candidates_for_run[: max(1, MAX_ITEMS_PER_RUN)]:
        eid = str(item.get("eid", "")).strip()
        analysis = analyses.get(eid)
        if not analysis:
            continue
        article = sync_pipeline.build_processed_article(
            item=item,
            analysis=analysis,
            now_iso=now,
            source_type=IC_SOURCE_TYPE,
        )
        processed[eid] = article
        article_records.append(article)

    if article_records:
        sync_pipeline.post_articles_in_chunks(
            api_url=IC_API_URL,
            request_post=requests.post,
            articles=[
                {
                    key: value
                    for key, value in row.items()
                    if key
                    in {
                        "source_type",
                        "source_feed_id",
                        "source_feed_name",
                        "source_article_id",
                        "title",
                        "url",
                        "pic_url",
                        "description",
                        "publish_time",
                        "tags",
                        "reason",
                        "actionable",
                        "hidden_signal",
                    }
                }
                for row in article_records
            ],
            chunk_size=5,
        )
        # 同时写入本地 PostgreSQL（可选，失败不影响主流程）
        try:
            save_articles(article_records)
        except Exception as e:
            log_event("WARN", "local_db_write_failed", stage="push", error=str(e))
        sync_pipeline.mark_articles_exported(processed, [row["id"] for row in article_records], now)
        stats["pushed"] = len(article_records)
        stats["push_attempted"] = len(article_records)

    # 全局 Agent 深度分析（如失败不影响主流程）
    try:
        run_global_analysis(analyses=analyses, candidates=candidates_for_run)
    except Exception as e:
        log_event("WARN", "global_agent_failed", stage="global_agent", error=str(e))

    apply_stage_metrics(stats, stage_metrics)
    stats["state_size"] = len(processed)
    write_step_summary(stats, os.getenv("GITHUB_STEP_SUMMARY", "").strip())
    log_event("INFO", "run_summary", stage="summary", **stats)
    print(f"Done. Exported {len(article_records)} items. State size={len(processed)}", flush=True)


if __name__ == "__main__":
    main()
