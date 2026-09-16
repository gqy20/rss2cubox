#!/usr/bin/env python3
import json
import os
import threading
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
        os.environ[key] = value.strip()


_load_local_env_file()

import requests

from rss2cubox import feed_sources, sync_pipeline
from rss2cubox import enrich_agent
from rss2cubox import fulltext_fetcher
from rss2cubox.db_client import save_articles, save_fulltext_batch, get_fulltexts_by_eids
from rss2cubox.db import record_feed_stat
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

# 日志文件：logs/runs/YYYY-MM-DD/HH-MM-SS.jsonl
_log_file: Any = None
_run_id = ""


def _get_log_file_path(now: datetime) -> Path:
    return Path("logs") / "runs" / now.strftime("%Y-%m-%d") / f"{now.strftime('%H-%M-%S')}.jsonl"


def _build_run_id(now: datetime) -> str:
    return (
        os.getenv("RSS2CUBOX_RUN_ID", "").strip()
        or os.getenv("GITHUB_RUN_ID", "").strip()
        or now.strftime("%Y%m%dT%H%M%S%z")
    )

IC_API_URL = os.getenv("IC_API_URL", "").strip()
IC_PUSH_ENABLED = os.getenv("IC_PUSH_ENABLED", "true").strip().lower() in ("1", "true", "yes")
IC_SOURCE_TYPE = os.getenv("IC_SOURCE_TYPE", "gqy").strip() or "gqy"
KEYWORDS_INCLUDE = [k.strip() for k in os.getenv("KEYWORDS_INCLUDE", "").split(",") if k.strip()]
KEYWORDS_EXCLUDE = [k.strip() for k in os.getenv("KEYWORDS_EXCLUDE", "").split(",") if k.strip()]
MAX_ITEMS_PER_RUN = int(os.getenv("MAX_ITEMS_PER_RUN", "300"))
# 单个源每轮最多贡献多少候选，0 = 不限流。
# 候选是 priority 降序 + 前缀截取，而各 feed 候选量差异极大（实测 openai 单 feed
# 1193 条、vercel 1578 条），不限流时一个高产源就能吃光整轮预算。
MAX_ITEMS_PER_SOURCE = max(0, sync_pipeline.env_int("MAX_ITEMS_PER_SOURCE", 60))
# enrich 结果增量落库的批大小。结果原本全程只在内存里，一轮要跑几小时，
# 中断就全丢（实测今天三次中断丢了 1501 篇的分析结果）。0 = 关闭增量落库。
ENRICH_FLUSH_EVERY = max(0, sync_pipeline.env_int("ENRICH_FLUSH_EVERY", 25))
# 全文增量落库的批大小。全文抓取一轮要 10~20 分钟，不增量写的话中断就全重抓。
FULLTEXT_FLUSH_EVERY = max(0, sync_pipeline.env_int("FULLTEXT_FLUSH_EVERY", 50))

ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "").strip()
FEED_CONNECT_TIMEOUT_SECONDS = sync_pipeline.env_float("FEED_CONNECT_TIMEOUT_SECONDS", 5.0)
FEED_READ_TIMEOUT_SECONDS = sync_pipeline.env_float("FEED_READ_TIMEOUT_SECONDS", 30.0)
FEED_FETCH_CONCURRENCY = max(1, sync_pipeline.env_int("FEED_FETCH_CONCURRENCY", 10))
WERSS_FETCH_CONCURRENCY = max(1, sync_pipeline.env_int("WERSS_FETCH_CONCURRENCY", 50))
RSSHUB_FAILURE_COOLDOWN_SECONDS = sync_pipeline.env_int("RSSHUB_FAILURE_COOLDOWN_SECONDS", 300)
RSSHUB_FAILURE_COOLDOWN_MAX_SECONDS = max(
    RSSHUB_FAILURE_COOLDOWN_SECONDS,
    sync_pipeline.env_int("RSSHUB_FAILURE_COOLDOWN_MAX_SECONDS", 3600),
)
RSSHUB_PREFLIGHT_ENABLED = os.getenv("RSSHUB_PREFLIGHT_ENABLED", "true").strip().lower() in ("1", "true", "yes")
RSSHUB_PREFLIGHT_TIMEOUT_SECONDS = sync_pipeline.env_float("RSSHUB_PREFLIGHT_TIMEOUT_SECONDS", 5.0)
FEED_SECTIONS_DISABLE = os.getenv("FEED_SECTIONS_DISABLE", "").strip()
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
        "run_id": _run_id,
    }
    payload.update(fields)
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    print(line, flush=True)
    if _log_file:
        _log_file.write(line + "\n")
        _log_file.flush()


def main() -> None:
    global _log_file, _run_id

    run_started_at = datetime.now()
    _run_id = _build_run_id(run_started_at)
    log_path = _get_log_file_path(run_started_at)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _log_file = open(log_path, "a", encoding="utf-8")

    feed_specs = feed_sources.load_feed_specs(FEEDS_FILE)
    feed_specs, _disabled_counts = feed_sources.filter_specs_by_buckets(
        feed_specs,
        FEED_SECTIONS_DISABLE,
        log_event=log_event,
    )
    rsshub_instances = feed_sources.load_rsshub_instances(RSSHUB_INSTANCES_FILE)
    rsshub_pool = RSSHubInstancePool(
        instances=rsshub_instances,
        cooldown_seconds=RSSHUB_FAILURE_COOLDOWN_SECONDS,
        max_cooldown_seconds=RSSHUB_FAILURE_COOLDOWN_MAX_SECONDS,
    )
    if RSSHUB_PREFLIGHT_ENABLED and rsshub_instances:
        feed_sources.preflight_instances(
            rsshub_pool,
            connect_timeout_seconds=min(FEED_CONNECT_TIMEOUT_SECONDS, 3.0),
            read_timeout_seconds=RSSHUB_PREFLIGHT_TIMEOUT_SECONDS,
            concurrency=FEED_FETCH_CONCURRENCY,
            log_event=log_event,
        )
    stage_metrics = StageMetrics()
    processed, feed_cursor = sync_pipeline.load_ic_state(
        api_url=IC_API_URL if IC_PUSH_ENABLED else "",
        source_type=IC_SOURCE_TYPE,
        request_get=requests.get,
    )
    feed_failures: dict[str, Any] = {}

    now = datetime.now(timezone.utc).isoformat()
    now_utc = datetime.now(timezone.utc)
    enabled = enrich_agent.ENRICH_AGENT_ENABLED
    runtime_context = build_runtime_context(
        run_id=_run_id,
        head_sha=os.getenv("GITHUB_SHA", ""),
        ref_name=os.getenv("GITHUB_REF_NAME", ""),
        event_name=os.getenv("GITHUB_EVENT_NAME", ""),
    )
    config_snapshot = build_config_snapshot(
        max_items_per_run=MAX_ITEMS_PER_RUN,
        ai_enabled=enabled,
        ai_model=ANTHROPIC_MODEL,
        ai_max_candidates=MAX_ITEMS_PER_RUN,
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
        ic_push_enabled=IC_PUSH_ENABLED,
    )

    _db_url = os.getenv("LOCAL_DB_URL", "").strip()
    _stat_recorder = None
    if _db_url:
        def _stat_recorder(**kw):
            record_feed_stat(_db_url, run_id=_run_id, **kw)
    # Initialize last_build_cache from previous runs (stored in feed_cursor)
    last_build_cache: dict[str, str] = {}
    for feed_url in feed_cursor:
        cached_lbd = feed_cursor[feed_url].get("last_build_date") if isinstance(feed_cursor[feed_url], dict) else None
        if cached_lbd:
            last_build_cache[feed_url] = cached_lbd

    candidates, updated_last_build_cache = feed_sources.collect_candidates_from_feeds(
        feed_specs=feed_specs,
        analyzed=processed,
        feed_cursor=feed_cursor,
        last_build_cache=last_build_cache,
        feed_failures=feed_failures,
        rsshub_pool=rsshub_pool,
        stats=stats,
        stage_metrics=stage_metrics,
        feed_fetch_concurrency=FEED_FETCH_CONCURRENCY,
        werss_fetch_concurrency=WERSS_FETCH_CONCURRENCY,
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
        record_stat=_stat_recorder,
    )
    # Update feed_cursor with last_build_cache for persistence
    for feed_url, lbd in updated_last_build_cache.items():
        if isinstance(feed_cursor.get(feed_url), dict):
            feed_cursor[feed_url]["last_build_date"] = lbd
        else:
            feed_cursor[feed_url] = {"last_build_date": lbd}

    candidates, run_deduped = sync_pipeline.dedupe_run_candidates(candidates, stats["per_feed_drop_reasons"])
    stats["run_deduped"] += run_deduped
    stats["candidates"] = len(candidates)

    candidates_for_run = feed_sources.cap_candidates_per_source(
        candidates,
        max_per_source=MAX_ITEMS_PER_SOURCE,
        max_total=MAX_ITEMS_PER_RUN,
    )
    stats["candidates_selected"] = len(candidates_for_run)
    _selected_sources = {str(c.get("source_feed", "")) for c in candidates_for_run}
    stats["sources_selected"] = len(_selected_sources)
    if len(candidates_for_run) < len(candidates):
        log_event(
            "INFO",
            "candidates_limited",
            stage="pre_push",
            selected=len(candidates_for_run),
            total=len(candidates),
            sources_selected=len(_selected_sources),
            max_per_source=MAX_ITEMS_PER_SOURCE,
        )

    # ── Phase 1: 原始文章元数据入库（不含全文）──
    # 必须在全文抓取**之前**：save_fulltext_batch 用的是 UPDATE ... WHERE id=eid，
    # 行不存在就写不进去。提前建行也让"抓到一篇就落一篇"成为可能。
    # 全文列这里不传，save_articles 会用 _optional_text 归一化成 NULL，
    # 而 ON CONFLICT 里的 COALESCE 会保住已有值，所以后续重跑不会把全文抹掉。
    if _db_url and candidates_for_run:
        _raw_articles = []
        for item in candidates_for_run:
            eid = str(item.get("eid", "")).strip()
            _raw_articles.append({
                "id": eid,
                "source_type": IC_SOURCE_TYPE,
                "source_feed_id": str(item.get("source_feed", "")).strip(),
                "source_feed_name": str(item.get("source_label", "")).strip() or str(item.get("source_feed", "")).strip() or "unknown",
                "source_article_id": str(item.get("source_article_id", "")).strip() or eid,
                "title": str(item.get("title", "")).strip(),
                "url": str(item.get("url", "")).strip(),
                "pic_url": str(item.get("cover_url", "")).strip(),
                "description": str(item.get("description", "")).strip(),
                "publish_time": str(item.get("publish_time", "")).strip(),
                "tags": [],
            })
        try:
            phase1_saved = save_articles(_raw_articles, db_url=_db_url)
            log_event("INFO", "phase1_raw_saved", stage="phase1", count=phase1_saved)
        except Exception as e:
            log_event("WARN", "phase1_save_failed", stage="phase1", error=str(e))

    # ── 全文抓取（边抓边增量落库）──
    ft_results: dict[str, Any] = {}
    if fulltext_fetcher.FULLTEXT_ENABLED and _db_url:
        _ft_buffer: dict[str, Any] = {}
        _ft_lock = threading.Lock()
        _ft_stats = {"saved": 0, "batches": 0, "lost": 0}

        def _flush_fulltext() -> None:
            if not _ft_buffer:
                return
            batch = dict(_ft_buffer)
            _ft_buffer.clear()
            try:
                save_fulltext_batch(batch, db_url=_db_url)
                _ft_stats["saved"] += len(batch)
                _ft_stats["batches"] += 1
                log_event(
                    "INFO", "fulltext_flush", stage="fulltext",
                    saved=len(batch), total_saved=_ft_stats["saved"],
                )
            except Exception as exc:  # noqa: BLE001
                _ft_stats["lost"] += len(batch)
                log_event(
                    "WARN", "fulltext_flush_error", stage="fulltext",
                    error=f"{type(exc).__name__}: {str(exc)[:180]}", lost=len(batch),
                )

        def _on_fulltext_result(eid: str, result: Any) -> None:
            if FULLTEXT_FLUSH_EVERY <= 0:
                return
            with _ft_lock:
                _ft_buffer[eid] = result
                if len(_ft_buffer) >= FULLTEXT_FLUSH_EVERY:
                    _flush_fulltext()

        log_event("INFO", "fulltext_start", stage="fulltext", count=len(candidates_for_run))
        ft_start = time.perf_counter()
        ft_results = fulltext_fetcher.fetch_fulltext_batch(
            candidates_for_run,
            max_workers=fulltext_fetcher.FULLTEXT_MAX_WORKERS,
            log_event=log_event,
            on_result=_on_fulltext_result,
        )
        with _ft_lock:
            _flush_fulltext()
        if FULLTEXT_FLUSH_EVERY > 0:
            stats["fulltext_flushed"] = _ft_stats["saved"]
            stats["fulltext_flush_lost"] = _ft_stats["lost"]
        ft_elapsed = time.perf_counter() - ft_start
        if ft_results:
            log_event(
                "INFO",
                "fulltext_fetched",
                stage="fulltext",
                fetched=len(ft_results),
                flushed=_ft_stats["saved"],
                duration_ms=int(ft_elapsed * 1000),
            )
        else:
            log_event("WARN", "fulltext_no_results", stage="fulltext")

    _pre_ft = {eid: r.text for eid, r in ft_results.items() if r.text} if ft_results else {}

    # ── DB fallback: 本轮没抓到的全文，从库里回补以前抓过的 ──
    # 旧条件是 `if not _pre_ft`（全有或全无）：只要本轮抓到了一篇，剩下缺的
    # 就永远不会回补。实测一次运行抓到 1473/1500，剩下 27 篇即使库里有历史
    # 全文也被跳过。改成只查缺失的 eid，并合并而不是覆盖。
    if _db_url and candidates_for_run:
        _missing_eids = [
            str(item.get("eid", "")).strip()
            for item in candidates_for_run
            if str(item.get("eid", "")).strip() and str(item.get("eid", "")).strip() not in _pre_ft
        ]
        if _missing_eids:
            _recovered = get_fulltexts_by_eids(_missing_eids, db_url=_db_url)
            if _recovered:
                _pre_ft.update(_recovered)
                log_event(
                    "INFO",
                    "fulltext_recovered_from_db",
                    stage="fulltext",
                    missing=len(_missing_eids),
                    recovered=len(_recovered),
                )

    # ── enrich 结果增量落库 ──
    # 每完成 ENRICH_FLUSH_EVERY 篇就写一次库，中断只损失未满一批的部分。
    # 写入用的是与 phase 2 完全相同的 build_processed_article + save_articles，
    # 而 save_articles 是 upsert 且 full_text 用 COALESCE 保护，所以幂等、不会吃掉全文。
    _flush_buffer: list[dict[str, Any]] = []
    _flush_lock = threading.Lock()
    _flush_stats = {"saved": 0, "batches": 0, "lost": 0}

    def _flush_now() -> None:
        if not _flush_buffer:
            return
        batch = list(_flush_buffer)
        _flush_buffer.clear()
        try:
            save_articles(batch, db_url=_db_url)
            _flush_stats["saved"] += len(batch)
            _flush_stats["batches"] += 1
            log_event(
                "INFO", "enrich_flush", stage="enrich",
                saved=len(batch), total_saved=_flush_stats["saved"],
            )
        except Exception as exc:  # noqa: BLE001
            _flush_stats["lost"] += len(batch)
            log_event(
                "WARN", "enrich_flush_error", stage="enrich",
                error=f"{type(exc).__name__}: {str(exc)[:180]}", lost=len(batch),
            )

    def _on_enrich_item_done(item: dict[str, Any], analysis: dict[str, Any]) -> None:
        """单篇 enrich 完成时的回调（在 anyio 工作线程里执行）。"""
        if not _db_url or ENRICH_FLUSH_EVERY <= 0:
            return
        if not sync_pipeline.has_signal_analysis(analysis):
            return
        record = sync_pipeline.build_processed_article(
            item=item, analysis=analysis, now_iso=now, source_type=IC_SOURCE_TYPE,
        )
        with _flush_lock:
            _flush_buffer.append(record)
            if len(_flush_buffer) >= ENRICH_FLUSH_EVERY:
                _flush_now()

    analyses = enrich_agent.analyze_candidates_with_agent(
        candidates=candidates_for_run,
        log_event=log_event,
        pre_fetched_texts=_pre_ft if _pre_ft else None,
        on_item_done=_on_enrich_item_done,
    )
    with _flush_lock:
        _flush_now()
    if ENRICH_FLUSH_EVERY > 0 and _db_url:
        stats["enrich_flushed"] = _flush_stats["saved"]
        stats["enrich_flush_lost"] = _flush_stats["lost"]
        log_event("INFO", "enrich_flush_summary", stage="enrich", **_flush_stats)
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
        if not sync_pipeline.has_signal_analysis(analysis):
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
        if IC_PUSH_ENABLED:
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
        else:
            log_event("INFO", "ic_push_skipped", stage="push", reason="IC_PUSH_ENABLED=false")
        # 写入本地 PostgreSQL（可选，失败不影响主流程）
        try:
            save_articles(article_records)
        except Exception as e:
            log_event("WARN", "local_db_write_failed", stage="push", error=str(e))
        sync_pipeline.mark_articles_exported(processed, [row["id"] for row in article_records], now)
        stats["pushed"] = len(article_records)
        stats["push_attempted"] = len(article_records)

    # 全局 Agent 深度分析（如失败不影响主流程）
    try:
        run_global_analysis(
            analyses=analyses,
            candidates=candidates_for_run,
            log_event=log_event,
            pre_fetched_texts=_pre_ft if _pre_ft else None,
        )
    except Exception as e:
        log_event("WARN", "global_agent_failed", stage="global_agent", error=str(e))

    apply_stage_metrics(stats, stage_metrics)
    stats["state_size"] = len(processed)
    write_step_summary(stats, os.getenv("GITHUB_STEP_SUMMARY", "").strip())
    log_event("INFO", "run_summary", stage="summary", **stats)
    print(f"Done. Exported {len(article_records)} items. State size={len(processed)}", flush=True)
    if _log_file:
        _log_file.close()
        _log_file = None


if __name__ == "__main__":
    main()
