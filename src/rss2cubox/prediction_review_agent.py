"""Claude Agent SDK powered Prediction Review Agent."""
from __future__ import annotations

import json
from functools import partial
from typing import Any

import anyio

from rss2cubox.agent_sdk_runner import _StructuredOutputError, _agent_timeout, _budget, extract_json_from_text, make_sdk_logger, run_json_agent, run_with_fallback


PREDICTION_REVIEW_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "prediction_id": {"type": "integer"},
        "score": {"type": "integer", "minimum": 1, "maximum": 5},
        "hit_level": {"type": "string", "enum": ["miss", "weak", "partial", "strong", "exact"]},
        "supporting_articles": {"type": "array", "items": {"type": "string"}},
        "contradicting_articles": {"type": "array", "items": {"type": "string"}},
        "actual_observation": {"type": "string"},
        "why_score": {"type": "string"},
        "improvement_advice": {"type": "string"},
        "review_metrics": {"type": "object"},
    },
    "required": [
        "prediction_id", "score", "hit_level", "supporting_articles",
        "contradicting_articles", "actual_observation", "why_score",
        "improvement_advice", "review_metrics",
    ],
}


SYSTEM_PROMPT = (
    "你是 Prediction Review Agent，负责在预测窗口结束后评估趋势预测是否命中。"
    "必须只使用输入文章作为支持或反证证据，不得臆造 article_id。"
    "评分标准：1=未命中，2=弱命中，3=部分命中，4=强命中，5=精确命中。"
    "输出必须符合 JSON Schema。"
)


def run_prediction_review_agent(
    prediction: dict[str, Any],
    articles: list[dict[str, Any]],
    *,
    log_event: Any | None = None,
) -> dict[str, Any]:
    prompt = json.dumps(
        {
            "prediction": prediction,
            "candidate_articles": articles,
            "instructions": [
                "supporting_articles 和 contradicting_articles 只能填输入文章 id。",
                "review_metrics 至少包含 support_count、source_count、avg_evidence_strength、contradiction_count。",
                "给出 why_score 和 improvement_advice，便于下一轮预测改进。",
            ],
        },
        ensure_ascii=False,
    )

    sdk_logger = make_sdk_logger("prediction_review", log_event=log_event,
                                prediction_id=prediction.get("id"),
                                article_count=len(articles))

    payload = anyio.run(
        partial(
            run_with_fallback,
            partial(
                run_json_agent,
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
                schema=PREDICTION_REVIEW_OUTPUT_SCHEMA,
                max_turns=20,
                max_budget_usd=_budget("PREDICTION_REVIEW_AGENT_MAX_BUDGET_USD", 10.0),
                timeout_seconds=_agent_timeout("PREDICTION_REVIEW_AGENT_TIMEOUT_SECONDS", default=300, minimum=120),
                sdk_log=sdk_logger,
            ),
            agent_name="prediction_review",
            validate=lambda d: "score" in d,
            sdk_log=log_event,
        )
    )

    return _validate_payload(payload, prediction, {str(article["id"]) for article in articles if article.get("id")})


def _validate_payload(payload: dict[str, Any], prediction: dict[str, Any], article_ids: set[str]) -> dict[str, Any]:
    if payload.get("prediction_id") != prediction.get("id"):
        payload["prediction_id"] = prediction.get("id")
    # 过滤无效 article id 而非丢弃全部
    for key in ("supporting_articles", "contradicting_articles"):
        values = payload.get(key)
        if isinstance(values, list):
            payload[key] = [v for v in values if str(v) in article_ids]
    return payload

# _budget 已抽取到 agent_sdk_runner._budget
