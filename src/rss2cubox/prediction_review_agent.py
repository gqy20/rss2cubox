"""Claude Agent SDK powered Prediction Review Agent."""
from __future__ import annotations

import json
from functools import partial
from typing import Any

import anyio

from rss2cubox.agent_sdk_runner import _StructuredOutputError, _agent_timeout, _budget, extract_json_from_text, make_sdk_logger, run_json_agent, run_with_fallback
from rss2cubox.prompt_registry import get, param

# system_prompt / 输出 schema / user 静态指令集中在项目根 prompts/prediction_review.yaml。
_PROMPT = get("prediction_review")

SYSTEM_PROMPT = _PROMPT.system_prompt
PREDICTION_REVIEW_OUTPUT_SCHEMA = _PROMPT.output_schema


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
            "instructions": _PROMPT.instructions_list,
        },
        ensure_ascii=False,
    )

    sdk_logger = make_sdk_logger("prediction_review", log_event=log_event,
                                prediction_id=prediction.get("id"),
                                article_count=len(articles),
                                prompt_version=_PROMPT.version)

    payload = anyio.run(
        partial(
            run_with_fallback,
            partial(
                run_json_agent,
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
                schema=PREDICTION_REVIEW_OUTPUT_SCHEMA,
                max_turns=param("prediction_review", "max_turns", 20),
                max_budget_usd=_budget("PREDICTION_REVIEW_AGENT_MAX_BUDGET_USD", param("prediction_review", "max_budget_usd", 10.0)),
                timeout_seconds=_agent_timeout(
                    "PREDICTION_REVIEW_AGENT_TIMEOUT_SECONDS",
                    default=param("prediction_review", "timeout_seconds", 900),
                    minimum=120,
                ),
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
