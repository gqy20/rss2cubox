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
    anthropic_messages_url,
    build_ai_items,
    build_ai_payload,
    extract_text_results,
    extract_tool_use_results,
)
from rss2cubox.feed_sources import RSSHubInstancePool
from rss2cubox.metrics import StageMetrics

FEEDS_FILE = Path(os.getenv("FEEDS_FILE", "feeds.txt"))
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
RSSHUB_INSTANCES_FILE = Path(os.getenv("RSSHUB_INSTANCES_FILE", "rsshub_instances.txt"))

CUBOX_API_URL = os.getenv("CUBOX_API_URL")
CUBOX_FOLDER = os.getenv("CUBOX_FOLDER", "RSS Inbox")
KEYWORDS_INCLUDE = [k.strip() for k in os.getenv("KEYWORDS_INCLUDE", "").split(",") if k.strip()]
KEYWORDS_EXCLUDE = [k.strip() for k in os.getenv("KEYWORDS_EXCLUDE", "").split(",") if k.strip()]
MAX_ITEMS_PER_RUN = int(os.getenv("MAX_ITEMS_PER_RUN", "20"))

ANTHROPIC_AUTH_TOKEN = os.getenv("ANTHROPIC_AUTH_TOKEN", "").strip()
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "").strip()


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


AI_MIN_SCORE = env_float("AI_MIN_SCORE", 0.6)
AI_TIMEOUT_SECONDS = env_int("AI_TIMEOUT_SECONDS", 90)
AI_RETRY_ATTEMPTS = env_int("AI_RETRY_ATTEMPTS", 3)
AI_RETRY_BACKOFF_SECONDS = env_float("AI_RETRY_BACKOFF_SECONDS", 1.5)
AI_BATCH_SIZE = env_int("AI_BATCH_SIZE", 5)
AI_MAX_CANDIDATES = env_int("AI_MAX_CANDIDATES", max(MAX_ITEMS_PER_RUN * 2, 1))
FEED_CONNECT_TIMEOUT_SECONDS = env_float("FEED_CONNECT_TIMEOUT_SECONDS", 5.0)
FEED_READ_TIMEOUT_SECONDS = env_float("FEED_READ_TIMEOUT_SECONDS", 10.0)
RSSHUB_FAILURE_COOLDOWN_SECONDS = env_int("RSSHUB_FAILURE_COOLDOWN_SECONDS", 300)


def log_event(level: str, event: str, **fields: Any) -> None:
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "event": event,
    }
    payload.update(fields)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str), flush=True)


def write_step_summary(summary: dict[str, Any]) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        return
    lines = [
        "## RSS2Cubox Run Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| feeds_total | {summary.get('feeds_total', 0)} |",
        f"| feeds_invalid | {summary.get('feeds_invalid', 0)} |",
        f"| rsshub_routes | {summary.get('rsshub_routes', 0)} |",
        f"| rsshub_fallback_used | {summary.get('rsshub_fallback_used', 0)} |",
        f"| rsshub_instances | {summary.get('rsshub_instances', 0)} |",
        f"| stage_fetch_total_ms | {summary.get('stage_fetch_total_ms', 0)} |",
        f"| stage_fetch_p95_ms | {summary.get('stage_fetch_p95_ms', 0)} |",
        f"| stage_ai_total_ms | {summary.get('stage_ai_total_ms', 0)} |",
        f"| stage_ai_p95_ms | {summary.get('stage_ai_p95_ms', 0)} |",
        f"| stage_push_total_ms | {summary.get('stage_push_total_ms', 0)} |",
        f"| stage_push_p95_ms | {summary.get('stage_push_p95_ms', 0)} |",
        f"| fetched | {summary.get('fetched', 0)} |",
        f"| deduped | {summary.get('deduped', 0)} |",
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


def fetch_and_parse_feed(url: str) -> Any:
    response = requests.get(
        url,
        timeout=(FEED_CONNECT_TIMEOUT_SECONDS, FEED_READ_TIMEOUT_SECONDS),
        headers={"user-agent": "rss2cubox/0.1 (+github-actions)"},
    )
    response.raise_for_status()
    import feedparser

    parsed = feedparser.parse(response.content)
    if getattr(parsed, "bozo", False):
        bozo_exc = getattr(parsed, "bozo_exception", None)
        raise ValueError(f"invalid feed parse: {bozo_exc!r}")
    return parsed


def parse_feed_with_fallback(
    feed_kind: str,
    feed_value: str,
    rsshub_pool: RSSHubInstancePool,
) -> tuple[str | None, Any | None, int]:
    candidates = feed_sources.resolve_feed_urls(feed_kind, feed_value, rsshub_pool)
    for idx, candidate_url in enumerate(candidates, start=1):
        instance = candidate_url.split("/", 3)[:3]
        instance_base = "/".join(instance) if len(instance) >= 3 else candidate_url
        if feed_kind == "rsshub" and rsshub_pool.should_skip(instance_base):
            log_event(
                "INFO",
                "feed_candidate_skipped_cooldown",
                stage="fetch",
                feed=feed_value,
                candidate=candidate_url,
                attempt=idx,
            )
            continue
        start = time.perf_counter()
        try:
            parsed = fetch_and_parse_feed(candidate_url)
            if feed_kind == "rsshub":
                rsshub_pool.mark_success(instance_base)
            duration_ms = int((time.perf_counter() - start) * 1000)
            log_event(
                "INFO",
                "feed_candidate_success",
                stage="fetch",
                feed=feed_value,
                candidate=candidate_url,
                attempt=idx,
                duration_ms=duration_ms,
            )
            if idx > 1:
                log_event(
                    "WARN",
                    "feed_fallback_used",
                    stage="fetch",
                    feed=feed_value,
                    selected=candidate_url,
                    attempt=idx,
                )
            return candidate_url, parsed, idx
        except Exception as exc:  # noqa: BLE001
            if feed_kind == "rsshub":
                rsshub_pool.mark_failure(instance_base)
            duration_ms = int((time.perf_counter() - start) * 1000)
            log_event(
                "WARN",
                "feed_candidate_failed",
                stage="fetch",
                feed=feed_value,
                candidate=candidate_url,
                attempt=idx,
                duration_ms=duration_ms,
                error=str(exc),
            )
    return None, None, 0


def ai_analysis_enabled() -> bool:
    return bool(ANTHROPIC_AUTH_TOKEN and ANTHROPIC_MODEL)


def _analyze_batch_with_ai(batch: list[dict], stage_metrics: StageMetrics) -> dict[str, dict]:
    if not batch or not ai_analysis_enabled():
        return {}

    items = build_ai_items(batch)
    headers = {
        "content-type": "application/json",
        "x-api-key": ANTHROPIC_AUTH_TOKEN,
        "anthropic-version": "2023-06-01",
        "authorization": f"Bearer {ANTHROPIC_AUTH_TOKEN}",
    }
    payload = build_ai_payload(ANTHROPIC_MODEL, items)

    batch_eids = [item.get("eid", "") for item in batch]
    for attempt in range(1, max(1, AI_RETRY_ATTEMPTS) + 1):
        start = time.perf_counter()
        try:
            response = requests.post(
                anthropic_messages_url(ANTHROPIC_BASE_URL),
                headers=headers,
                json=payload,
                timeout=AI_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
            duration_ms = int((time.perf_counter() - start) * 1000)
            stage_metrics.observe("ai", duration_ms)
            stop_reason = data.get("stop_reason")
            block_types = [block.get("type") for block in data.get("content", []) if isinstance(block, dict)]
            usage = data.get("usage", {})
            log_event(
                "INFO",
                "ai_batch_response",
                stage="ai_analyze",
                batch_size=len(batch),
                attempt=attempt,
                duration_ms=duration_ms,
                stop_reason=stop_reason,
                block_types=block_types,
                usage=usage,
            )
            parsed = extract_tool_use_results(data)
            if parsed:
                return parsed
            # Compatibility fallback for gateways that return plain text JSON.
            parsed = extract_text_results(data)
            if parsed:
                return parsed
            raise ValueError("empty or unrecognized AI output")
        except Exception as exc:  # noqa: BLE001
            duration_ms = int((time.perf_counter() - start) * 1000)
            stage_metrics.observe("ai", duration_ms)
            if attempt >= max(1, AI_RETRY_ATTEMPTS):
                log_event(
                    "WARN",
                    "ai_batch_failed",
                    stage="ai_analyze",
                    attempts=attempt,
                    batch_size=len(batch),
                    duration_ms=duration_ms,
                    eids_preview=batch_eids[:3],
                    error=str(exc),
                )
                return {}
            sleep_seconds = AI_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
            log_event(
                "WARN",
                "ai_batch_retrying",
                stage="ai_analyze",
                attempt=attempt,
                batch_size=len(batch),
                duration_ms=duration_ms,
                retry_in_seconds=round(sleep_seconds, 3),
                error=str(exc),
            )
            time.sleep(sleep_seconds)
    return {}


def analyze_candidates_with_ai(candidates: list[dict], stage_metrics: StageMetrics | None = None) -> dict[str, dict]:
    if not candidates or not ai_analysis_enabled():
        return {}
    metrics = stage_metrics or StageMetrics()
    batch_size = max(1, AI_BATCH_SIZE)
    out: dict[str, dict] = {}
    total = len(candidates)
    batches = (total + batch_size - 1) // batch_size
    for idx in range(0, total, batch_size):
        batch = candidates[idx : idx + batch_size]
        batch_no = idx // batch_size + 1
        log_event(
            "INFO",
            "ai_batch_start",
            stage="ai_analyze",
            batch_no=batch_no,
            batches=batches,
            batch_size=len(batch),
        )
        parsed = _analyze_batch_with_ai(batch, metrics)
        out.update(parsed)
    if out:
        log_event("INFO", "ai_analyze_done", stage="ai_analyze", analyzed=len(out), total=total)
    else:
        log_event("WARN", "ai_analyze_empty", stage="ai_analyze", total=total)
    return out


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

    candidates: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()
    stats: dict[str, Any] = {
        "feeds_total": len(feed_specs),
        "feeds_invalid": 0,
        "rsshub_routes": 0,
        "rsshub_fallback_used": 0,
        "rsshub_instances": len(rsshub_instances),
        "stage_fetch_total_ms": 0,
        "stage_fetch_p95_ms": 0,
        "stage_ai_total_ms": 0,
        "stage_ai_p95_ms": 0,
        "stage_push_total_ms": 0,
        "stage_push_p95_ms": 0,
        "fetched": 0,
        "deduped": 0,
        "missing_link": 0,
        "keyword_filtered": 0,
        "candidates": 0,
        "candidates_selected": 0,
        "ai_enabled": ai_analysis_enabled(),
        "ai_analyzed": 0,
        "ai_missing": 0,
        "ai_kept": 0,
        "ai_dropped_keep_false": 0,
        "ai_dropped_score": 0,
        "push_attempted": 0,
        "pushed": 0,
        "push_failed": 0,
        "state_size": 0,
        "runtime_context": {
            "run_id": os.getenv("GITHUB_RUN_ID", ""),
            "head_sha": os.getenv("GITHUB_SHA", ""),
            "ref_name": os.getenv("GITHUB_REF_NAME", ""),
            "event_name": os.getenv("GITHUB_EVENT_NAME", ""),
        },
        "config_snapshot": {
            "max_items_per_run": MAX_ITEMS_PER_RUN,
            "ai_enabled": ai_analysis_enabled(),
            "ai_model": ANTHROPIC_MODEL if ai_analysis_enabled() else "",
            "ai_min_score": AI_MIN_SCORE,
            "ai_timeout_seconds": AI_TIMEOUT_SECONDS,
            "ai_retry_attempts": AI_RETRY_ATTEMPTS,
            "ai_batch_size": AI_BATCH_SIZE,
            "ai_max_candidates": AI_MAX_CANDIDATES,
            "feed_connect_timeout_seconds": FEED_CONNECT_TIMEOUT_SECONDS,
            "feed_read_timeout_seconds": FEED_READ_TIMEOUT_SECONDS,
            "rsshub_failure_cooldown_seconds": RSSHUB_FAILURE_COOLDOWN_SECONDS,
        },
        "per_feed_push_counts": {},
        "per_feed_drop_reasons": {},
    }
    log_event(
        "INFO",
        "run_start",
        stage="start",
        feeds_total=stats["feeds_total"],
        max_items_per_run=MAX_ITEMS_PER_RUN,
        rsshub_instances=stats["rsshub_instances"],
        ai_enabled=stats["ai_enabled"],
        ai_model=ANTHROPIC_MODEL if stats["ai_enabled"] else "",
    )

    for spec in feed_specs:
        feed_kind = spec["kind"]
        feed_url = spec["value"]
        feed_seen = 0
        feed_candidates = 0
        feed_start = time.perf_counter()
        if feed_kind == "rsshub":
            stats["rsshub_routes"] += 1
        log_event("INFO", "feed_fetch_start", stage="fetch", feed=feed_url, kind=feed_kind)
        selected_url, parsed, selected_attempt = parse_feed_with_fallback(feed_kind, feed_url, rsshub_pool)
        if selected_url is None or parsed is None:
            stats["feeds_invalid"] += 1
            log_event("WARN", "feed_invalid", stage="fetch", feed=feed_url, kind=feed_kind)
            continue
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

        for entry in parsed.entries:
            feed_seen += 1
            stats["fetched"] += 1
            eid = sync_pipeline.stable_id(entry)
            if eid in sent:
                stats["deduped"] += 1
                continue
            if not entry.get("link"):
                stats["missing_link"] += 1
                continue
            if not sync_pipeline.passes_filter(entry, KEYWORDS_INCLUDE, KEYWORDS_EXCLUDE):
                stats["keyword_filtered"] += 1
                continue

            url = entry["link"]
            title = entry.get("title", "") or ""
            description = (entry.get("summary", "") or "").strip()
            if len(description) > 600:
                description = description[:600] + "..."
            candidates.append(
                {
                    "eid": eid,
                    "url": url,
                    "title": title,
                    "description": description,
                    "source_feed": feed_url,
                }
            )
            feed_candidates += 1
        feed_duration_ms = int((time.perf_counter() - feed_start) * 1000)
        stage_metrics.observe("fetch", feed_duration_ms)
        log_event(
            "INFO",
            "feed_processed",
            stage="fetch",
            feed=feed_url,
            kind=feed_kind,
            resolved_url=selected_url,
            fetched=feed_seen,
            candidates=feed_candidates,
            duration_ms=feed_duration_ms,
        )

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

    analyses = analyze_candidates_with_ai(candidates_for_run, stage_metrics)
    stats["ai_analyzed"] = len(analyses)
    ai_enabled = stats["ai_enabled"]
    if ai_enabled and analyses:
        missing = sum(1 for item in candidates_for_run if item["eid"] not in analyses)
        stats["ai_missing"] = missing
        if missing:
            log_event("WARN", "ai_missing_results", stage="ai_analyze", missing=missing)

    for item in candidates_for_run:
        if stats["pushed"] >= MAX_ITEMS_PER_RUN:
            break

        eid = item["eid"]
        url = item["url"]
        title = item["title"]
        description = item["description"]
        tags = None
        source_feed = item.get("source_feed", "unknown")

        result = analyses.get(eid)
        if ai_enabled and analyses and not result:
            drop_by_feed = stats["per_feed_drop_reasons"].setdefault(source_feed, {})
            drop_by_feed["missing_ai_result"] = drop_by_feed.get("missing_ai_result", 0) + 1
            log_event(
                "INFO",
                "candidate_skipped",
                stage="ai_decision",
                item_id=eid,
                url=url,
                action="drop",
                reason="missing_ai_result",
            )
            continue
        if result:
            keep = bool(result.get("keep", False))
            score = float(result.get("score", 0.0))
            reason = str(result.get("reason", ""))
            action = "keep" if keep and score >= AI_MIN_SCORE else "drop"
            log_event(
                "INFO",
                "ai_item_decision",
                stage="ai_decision",
                item_id=eid,
                url=url,
                action=action,
                keep=keep,
                score=score,
                threshold=AI_MIN_SCORE,
                reason=reason,
            )
            ai[eid] = {
                "keep": keep,
                "score": score,
                "reason": reason,
                "ts": now,
                "model": ANTHROPIC_MODEL,
            }
            if not keep:
                stats["ai_dropped_keep_false"] += 1
                drop_by_feed = stats["per_feed_drop_reasons"].setdefault(source_feed, {})
                drop_by_feed["ai_keep_false"] = drop_by_feed.get("ai_keep_false", 0) + 1
                continue
            if score < AI_MIN_SCORE:
                stats["ai_dropped_score"] += 1
                drop_by_feed = stats["per_feed_drop_reasons"].setdefault(source_feed, {})
                drop_by_feed["ai_score_below_threshold"] = drop_by_feed.get("ai_score_below_threshold", 0) + 1
                continue
            stats["ai_kept"] += 1
            brief = str(result.get("brief", "")).strip()
            if brief:
                description = brief[:600]
            if result.get("tags"):
                tags = result["tags"]

        stats["push_attempted"] += 1
        push_start = time.perf_counter()
        try:
            sync_pipeline.cubox_save_url(
                api_url=CUBOX_API_URL,
                request_post=requests.post,
                url=url,
                title=title,
                description=description,
                tags=tags,
                folder=CUBOX_FOLDER,
            )
            sent[eid] = {"url": url, "ts": now}
            stats["pushed"] += 1
            stats["per_feed_push_counts"][source_feed] = stats["per_feed_push_counts"].get(source_feed, 0) + 1
            push_duration_ms = int((time.perf_counter() - push_start) * 1000)
            stage_metrics.observe("push", push_duration_ms)
            log_event(
                "INFO",
                "push_success",
                stage="push",
                item_id=eid,
                url=url,
                duration_ms=push_duration_ms,
            )
            time.sleep(0.3)
        except Exception as exc:  # noqa: BLE001
            stats["push_failed"] += 1
            push_duration_ms = int((time.perf_counter() - push_start) * 1000)
            stage_metrics.observe("push", push_duration_ms)
            drop_by_feed = stats["per_feed_drop_reasons"].setdefault(source_feed, {})
            drop_by_feed["push_failed"] = drop_by_feed.get("push_failed", 0) + 1
            log_event(
                "ERROR",
                "push_failed",
                stage="push",
                item_id=eid,
                url=url,
                duration_ms=push_duration_ms,
                error=str(exc),
            )

    state["sent"] = sent
    state["ai"] = ai
    sync_pipeline.save_state(STATE_FILE, state)
    stats["stage_fetch_total_ms"] = stage_metrics.total_ms("fetch")
    stats["stage_fetch_p95_ms"] = stage_metrics.p95_ms("fetch")
    stats["stage_ai_total_ms"] = stage_metrics.total_ms("ai")
    stats["stage_ai_p95_ms"] = stage_metrics.p95_ms("ai")
    stats["stage_push_total_ms"] = stage_metrics.total_ms("push")
    stats["stage_push_p95_ms"] = stage_metrics.p95_ms("push")
    stats["state_size"] = len(sent)
    write_step_summary(stats)
    log_event("INFO", "run_summary", stage="summary", **stats)
    print(f"Done. Pushed {stats['pushed']} items. State size={len(sent)}", flush=True)


if __name__ == "__main__":
    main()
