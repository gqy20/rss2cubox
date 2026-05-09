"""Claude Agent SDK powered Trend Prediction Agent."""
from __future__ import annotations

import json
from functools import partial
from datetime import datetime, timedelta, timezone
from typing import Any

import anyio

from rss2cubox.agent_sdk_runner import _StructuredOutputError, _budget, extract_json_from_text, make_sdk_logger, run_json_agent


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
    "你是 AI 趋势预测 Agent，尤其深耕 AI 与智能体（AI Agent）领域，负责基于 signal_clusters 生成未来可验证的趋势预测。"
    "预测必须绑定输入中的 signal_cluster_key，必须可证伪，不能输出泛泛趋势。"
    "expected_evidence 必须包含 minimum_support_count、required_source_count、required_evidence_types。"
    "必须参考 historical_reviews，避免重复低质量预测，并吸收 improvement_advice 调整证据门槛。"
    "prediction_type: 1=延续预测，2=转阶段预测，3=扩散预测，4=反转预测，5=迟到验证。"
    "【关注重点】在挑选预测目标时，优先考虑以下方向的 cluster：\n"
    "- AI 模型能力突破（新架构、新基准、Scaling Law 变化）\n"
    "- AI Agent / 智能体框架、工具链、多智能体协作\n"
    "- LLM 应用层创新（RAG、推理优化、长上下文、多模态）\n"
    "- 开源模型与生态动态（权重开源、微调方案、社区趋势）\n"
    "- AI 基础设施（算力、芯片、推理优化、训练框架）\n"
    "以上方向在其他条件相同时应优先被选为预测目标，但不要为了凑数而强行选择弱信号。\n"
    "【评分利用】每个 cluster 都带有聚合评分字段，请据此筛选：\n"
    "- 优先选择 avg_importance 高（≥3.5）的 cluster，这类信号重要性高\n"
    "- avg_confidence 低的 cluster（<3）即使 importance 高也应降低优先级或提高证据门槛\n"
    "- 避免对同一 normalized_label 或相似 entities 的 cluster 反复预测，除非有明确的新进展信号\n"
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
                "只从输入 clusters 中选择值得预测的信号，优先选择 AI/智能体方向且评分高的 cluster。",
                "每条预测必须绑定 signal_cluster_key。",
                "利用 cluster 的 avg_importance、avg_confidence 做筛选排序，不要忽略这些字段。",
                "参考 historical_reviews 中的 score、why_score、improvement_advice，避免重复已失败模式。",
                "不要输出超过 max_predictions 条。",
            ],
        },
        ensure_ascii=False,
    )

    sdk_logger = make_sdk_logger("trend_prediction", log_event=log_event,
                                cluster_count=len(clusters),
                                historical_review_count=len(historical_reviews or []),
                                max_predictions=max_predictions)

    try:
        payload = anyio.run(partial(
            run_json_agent,
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
            schema=TREND_PREDICTION_OUTPUT_SCHEMA,
            max_turns=20,
            max_budget_usd=_budget("TREND_PREDICTION_AGENT_MAX_BUDGET_USD", 10.0),
            sdk_log=sdk_logger,
        ))
    except _StructuredOutputError as e:
        if log_event:
            log_event("WARN", "trend_prediction_fallback_start", stage="agent_sdk", agent="trend_prediction")
        fallback = extract_json_from_text(e.raw_text)
        if isinstance(fallback, dict) and isinstance(fallback.get("predictions"), list):
            payload = fallback
            if log_event:
                log_event("INFO", "trend_prediction_fallback_ok", stage="agent_sdk", agent="trend_prediction",
                          prediction_count=len(payload.get("predictions", [])))
        else:
            if log_event:
                log_event("WARN", "trend_prediction_fallback_failed", stage="agent_sdk", agent="trend_prediction",
                          raw_preview=e.raw_text[:300])
            raise

    predictions = payload.get("predictions")
    if not isinstance(predictions, list):
        raise RuntimeError("invalid_trend_prediction_payload")
    # 过滤无效 prediction 而非丢弃全部
    valid_keys = {str(cluster.get("cluster_key")) for cluster in clusters if cluster.get("cluster_key")}
    valid = [p for p in predictions if str(p.get("signal_cluster_key")) in valid_keys]
    return valid[:max_predictions]

# _budget 已抽取到 agent_sdk_runner._budget
