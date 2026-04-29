"""Claude Agent SDK powered Prediction Review Agent."""
from __future__ import annotations

import json
import os
from functools import partial
from typing import Any

import anyio

from rss2cubox.agent_sdk_runner import run_json_agent


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

    def sdk_logger(event: str, **fields: Any) -> None:
        if log_event is None:
            return
        level = "WARN" if event.endswith("_error") or event == "agent_sdk_no_result" else "INFO"
        log_event(
            level,
            event,
            stage="agent_sdk",
            agent="prediction_review",
            prediction_id=prediction.get("id"),
            article_count=len(articles),
            **fields,
        )

    payload = anyio.run(partial(
        run_json_agent,
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT,
        schema=PREDICTION_REVIEW_OUTPUT_SCHEMA,
        max_turns=20,
        max_budget_usd=_budget("PREDICTION_REVIEW_AGENT_MAX_BUDGET_USD", 10.0),
        sdk_log=sdk_logger,
    ))
    return _validate_payload(payload, prediction, {str(article["id"]) for article in articles if article.get("id")})


def _validate_payload(payload: dict[str, Any], prediction: dict[str, Any], article_ids: set[str]) -> dict[str, Any]:
    if payload.get("prediction_id") != prediction.get("id"):
        payload["prediction_id"] = prediction.get("id")
    for key in ("supporting_articles", "contradicting_articles"):
        values = payload.get(key)
        if not isinstance(values, list):
            raise RuntimeError("invalid_prediction_review_payload")
        unknown = [value for value in values if str(value) not in article_ids]
        if unknown:
            raise RuntimeError("prediction_review_unknown_article")
    return payload


def _budget(name: str, default: float) -> float | None:
    raw = os.getenv(name, str(default)).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return default
