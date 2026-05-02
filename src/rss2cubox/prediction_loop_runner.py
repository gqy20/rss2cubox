"""Run the local signal prediction loop after the RSS sync."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from rss2cubox.db_client import (
    ensure_prediction_loop_schema,
    get_due_trend_predictions,
    get_existing_signal_clusters,
    get_prediction_window_articles,
    get_recent_enriched_articles,
    get_recent_prediction_reviews,
    get_signal_clusters_for_prediction,
    save_prediction_review,
    save_signal_clusters,
    save_trend_predictions,
)
from rss2cubox.prediction_agent import run_trend_prediction_agent
from rss2cubox.prediction_review_agent import run_prediction_review_agent
from rss2cubox.signal_cluster_agent import run_signal_cluster_agent


load_dotenv(override=True)

PREDICTION_LOOP_ENABLED = os.getenv("PREDICTION_LOOP_ENABLED", "true").lower() not in ("false", "0", "no")
PREDICTION_LOOP_ARTICLE_DAYS = max(1, int(os.getenv("PREDICTION_LOOP_ARTICLE_DAYS", "30")))
PREDICTION_LOOP_ARTICLE_LIMIT = max(1, int(os.getenv("PREDICTION_LOOP_ARTICLE_LIMIT", "500")))
PREDICTION_LOOP_CLUSTER_LIMIT = max(1, int(os.getenv("PREDICTION_LOOP_CLUSTER_LIMIT", "20")))
PREDICTION_LOOP_MAX_PREDICTIONS = max(1, int(os.getenv("PREDICTION_LOOP_MAX_PREDICTIONS", "3")))
PREDICTION_LOOP_REVIEW_LIMIT = max(1, int(os.getenv("PREDICTION_LOOP_REVIEW_LIMIT", "20")))
PREDICTION_LOOP_REVIEW_ARTICLE_LIMIT = max(1, int(os.getenv("PREDICTION_LOOP_REVIEW_ARTICLE_LIMIT", "200")))
PREDICTION_LOOP_EXISTING_CLUSTER_LIMIT = max(1, int(os.getenv("PREDICTION_LOOP_EXISTING_CLUSTER_LIMIT", "200")))
PREDICTION_LOOP_REVIEW_HISTORY_LIMIT = max(1, int(os.getenv("PREDICTION_LOOP_REVIEW_HISTORY_LIMIT", "150")))
PREDICTION_CLUSTER_INTERVAL_HOURS = max(1, int(os.getenv("PREDICTION_CLUSTER_INTERVAL_HOURS", "24")))
PREDICTION_GENERATE_INTERVAL_HOURS = max(1, int(os.getenv("PREDICTION_GENERATE_INTERVAL_HOURS", "72")))
PREDICTION_REVIEW_INTERVAL_HOURS = max(1, int(os.getenv("PREDICTION_REVIEW_INTERVAL_HOURS", "24")))
PREDICTION_LOOP_STATE_DIR = Path(os.getenv("PREDICTION_LOOP_STATE_DIR", ".rss2cubox-prediction-loop"))
FORCE_PREDICTION_LOOP = os.getenv("RSS2CUBOX_FORCE_PREDICTION_LOOP", "false").lower() in ("1", "true", "yes")


def log_event(level: str, event: str, **fields: Any) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "event": event,
        "run_id": os.getenv("RSS2CUBOX_RUN_ID", ""),
    }
    payload.update(fields)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str), flush=True)


def _stage_due(stage: str, interval_hours: int) -> bool:
    if FORCE_PREDICTION_LOOP:
        return True
    marker = PREDICTION_LOOP_STATE_DIR / f"{stage}.last_run"
    if not marker.exists():
        return True
    age_seconds = datetime.now(timezone.utc).timestamp() - marker.stat().st_mtime
    return age_seconds >= interval_hours * 3600


def _force_stage_due(stage: str) -> None:
    """删除 stage 的 marker 文件，使其在下次检查时强制触发。"""
    marker = PREDICTION_LOOP_STATE_DIR / f"{stage}.last_run"
    if marker.exists():
        marker.unlink()


def _mark_stage_done(stage: str) -> None:
    PREDICTION_LOOP_STATE_DIR.mkdir(parents=True, exist_ok=True)
    marker = PREDICTION_LOOP_STATE_DIR / f"{stage}.last_run"
    marker.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")


def main() -> None:
    if not PREDICTION_LOOP_ENABLED:
        log_event("INFO", "prediction_loop_skipped", reason="disabled")
        return

    if not ensure_prediction_loop_schema():
        log_event("WARN", "prediction_loop_skipped", reason="missing_local_db")
        return

    log_event("INFO", "prediction_loop_start")
    stats = {
        "articles": 0,
        "clusters": 0,
        "links": 0,
        "predictions": 0,
        "reviews": 0,
    }

    if _stage_due("cluster", PREDICTION_CLUSTER_INTERVAL_HOURS):
        try:
            articles = get_recent_enriched_articles(
                days=PREDICTION_LOOP_ARTICLE_DAYS,
                limit=PREDICTION_LOOP_ARTICLE_LIMIT,
            )
            stats["articles"] = len(articles)
            if articles:
                existing_clusters = get_existing_signal_clusters(limit=PREDICTION_LOOP_EXISTING_CLUSTER_LIMIT)
                cluster_result = run_signal_cluster_agent(
                    articles,
                    existing_clusters=existing_clusters,
                    log_event=log_event,
                )
                cluster_ids = save_signal_clusters(cluster_result)
                stats["clusters"] = len(cluster_result.get("clusters", []))
                stats["links"] = len(cluster_result.get("links", []))
                # cluster 产出了新结果 → 级联触发 generate（删除 marker 使其立即 due）
                if cluster_ids:
                    _force_stage_due("generate")
            else:
                cluster_ids = {}
            _mark_stage_done("cluster")
        except Exception as e:
            cluster_ids = {}
            log_event("WARN", "prediction_cluster_failed", error=str(e))
    else:
        cluster_ids = {}
        log_event("INFO", "prediction_stage_skipped", stage="cluster", interval_hours=PREDICTION_CLUSTER_INTERVAL_HOURS)

    if _stage_due("review", PREDICTION_REVIEW_INTERVAL_HOURS):
        try:
            due_predictions = get_due_trend_predictions(limit=PREDICTION_LOOP_REVIEW_LIMIT)
            for prediction in due_predictions:
                articles = get_prediction_window_articles(prediction, limit=PREDICTION_LOOP_REVIEW_ARTICLE_LIMIT)
                review = run_prediction_review_agent(prediction, articles, log_event=log_event)
                if save_prediction_review(review):
                    stats["reviews"] += 1
            _mark_stage_done("review")
        except Exception as e:
            log_event("WARN", "prediction_review_failed", error=str(e))
    else:
        log_event("INFO", "prediction_stage_skipped", stage="review", interval_hours=PREDICTION_REVIEW_INTERVAL_HOURS)

    if _stage_due("generate", PREDICTION_GENERATE_INTERVAL_HOURS):
        try:
            clusters = get_signal_clusters_for_prediction(limit=PREDICTION_LOOP_CLUSTER_LIMIT)
            if clusters:
                historical_reviews = get_recent_prediction_reviews(limit=PREDICTION_LOOP_REVIEW_HISTORY_LIMIT)
                predictions = run_trend_prediction_agent(
                    clusters,
                    historical_reviews=historical_reviews,
                    max_predictions=PREDICTION_LOOP_MAX_PREDICTIONS,
                    log_event=log_event,
                )
                if predictions:
                    if not cluster_ids:
                        cluster_ids = {str(cluster.get("cluster_key")): int(cluster["id"]) for cluster in clusters if cluster.get("id")}
                    stats["predictions"] = save_trend_predictions(predictions, cluster_ids)
            _mark_stage_done("generate")
        except Exception as e:
            log_event("WARN", "trend_prediction_failed", error=str(e))
    else:
        log_event("INFO", "prediction_stage_skipped", stage="generate", interval_hours=PREDICTION_GENERATE_INTERVAL_HOURS)

    log_event("INFO", "prediction_loop_complete", **stats)


if __name__ == "__main__":
    main()
