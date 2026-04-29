"""Claude Agent SDK powered Trend Prediction Agent."""
from __future__ import annotations

import json
import os
from functools import partial
from datetime import datetime, timedelta, timezone
from typing import Any

import anyio

from rss2cubox.agent_sdk_runner import run_json_agent


TREND_PREDICTION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "predictions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "signal_cluster_key": {"type": "string"},
                    "prediction_type": {"type": "integer", "minimum": 1, "maximum": 5},
                    "created_at": {"type": "string"},
                    "target_start_at": {"type": "string"},
                    "target_end_at": {"type": "string"},
                    "horizon_days": {"type": "integer", "minimum": 1},
                    "prediction_title": {"type": "string"},
                    "prediction_body": {"type": "string"},
                    "watch_keywords": {"type": "array", "items": {"type": "string"}},
                    "expected_evidence": {"type": "object"},
                    "disconfirming_evidence": {"type": "string"},
                    "baseline_metrics": {"type": "object"},
                    "confidence": {"type": "integer", "minimum": 1, "maximum": 5},
                    "status": {"type": "string", "enum": ["pending"]},
                },
                "required": [
                    "signal_cluster_key", "prediction_type", "created_at", "target_start_at",
                    "target_end_at", "horizon_days", "prediction_title", "prediction_body",
                    "watch_keywords", "expected_evidence", "disconfirming_evidence",
                    "baseline_metrics", "confidence", "status",
                ],
            },
        },
    },
    "required": ["predictions"],
}


SYSTEM_PROMPT = (
    "你是 Trend Prediction Agent，负责基于历史 signal_clusters 生成未来一周可验证 AI 趋势预测。"
    "预测必须绑定输入中的 signal_cluster_key，必须可证伪，不能输出泛泛趋势。"
    "expected_evidence 必须包含 minimum_support_count、required_source_count、required_evidence_types。"
    "必须参考 historical_reviews，避免重复低质量预测，并吸收 improvement_advice 调整证据门槛。"
    "prediction_type: 1=延续预测，2=转阶段预测，3=扩散预测，4=反转预测，5=迟到验证。"
    "只输出符合 JSON Schema 的结构化结果。"
)


def run_trend_prediction_agent(
    clusters: list[dict[str, Any]],
    *,
    historical_reviews: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
    horizon_days: int = 7,
    max_predictions: int = 5,
    log_event: Any | None = None,
) -> list[dict[str, Any]]:
    if not clusters:
        return []

    now_dt = now or datetime.now(timezone.utc)
    target_end = now_dt + timedelta(days=horizon_days)
    prompt = json.dumps(
        {
            "now": now_dt.isoformat(),
            "target_end_at": target_end.isoformat(),
            "horizon_days": horizon_days,
            "max_predictions": max_predictions,
            "clusters": clusters,
            "historical_reviews": historical_reviews or [],
            "instructions": [
                "只从输入 clusters 中选择值得预测的信号。",
                "每条预测必须绑定 signal_cluster_key。",
                "参考 historical_reviews 中的 score、why_score、improvement_advice，避免重复已失败模式。",
                "不要输出超过 max_predictions 条。",
            ],
        },
        ensure_ascii=False,
    )

    def sdk_logger(event: str, **fields: Any) -> None:
        if log_event is None:
            return
        level = "WARN" if event.endswith("_error") or event == "agent_sdk_no_result" else "INFO"
        log_event(
            level,
            event,
            stage="agent_sdk",
            agent="trend_prediction",
            cluster_count=len(clusters),
            historical_review_count=len(historical_reviews or []),
            max_predictions=max_predictions,
            **fields,
        )

    payload = anyio.run(partial(
        run_json_agent,
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT,
        schema=TREND_PREDICTION_OUTPUT_SCHEMA,
        max_turns=20,
        max_budget_usd=_budget("TREND_PREDICTION_AGENT_MAX_BUDGET_USD", 10.0),
        sdk_log=sdk_logger,
    ))
    predictions = payload.get("predictions")
    if not isinstance(predictions, list):
        raise RuntimeError("invalid_trend_prediction_payload")
    valid_keys = {str(cluster.get("cluster_key")) for cluster in clusters if cluster.get("cluster_key")}
    for prediction in predictions:
        if str(prediction.get("signal_cluster_key")) not in valid_keys:
            raise RuntimeError("prediction_unknown_cluster")
    return predictions[:max_predictions]


def _budget(name: str, default: float) -> float | None:
    raw = os.getenv(name, str(default)).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return default
