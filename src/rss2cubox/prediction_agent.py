"""Claude Agent SDK powered Trend Prediction Agent."""
from __future__ import annotations

import json
from functools import partial
from datetime import datetime, timedelta, timezone
from typing import Any

import anyio

from rss2cubox.agent_sdk_runner import _StructuredOutputError, _agent_timeout, _budget, extract_json_from_text, make_sdk_logger, run_json_agent, run_with_fallback
from rss2cubox.prompt_registry import get, param

# system_prompt / 输出 schema / user 静态指令集中在项目根 prompts/prediction.yaml。
_PROMPT = get("prediction")

SYSTEM_PROMPT = _PROMPT.system_prompt
TREND_PREDICTION_OUTPUT_SCHEMA = _PROMPT.output_schema


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
            "instructions": _PROMPT.instructions_list,
        },
        ensure_ascii=False,
    )

    sdk_logger = make_sdk_logger("trend_prediction", log_event=log_event,
                                cluster_count=len(clusters),
                                historical_review_count=len(historical_reviews or []),
                                max_predictions=max_predictions,
                                prompt_version=_PROMPT.version)

    payload = anyio.run(
        partial(
            run_with_fallback,
            partial(
                run_json_agent,
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
                schema=TREND_PREDICTION_OUTPUT_SCHEMA,
                max_turns=param("prediction", "max_turns", 20),
                max_budget_usd=_budget("TREND_PREDICTION_AGENT_MAX_BUDGET_USD", param("prediction", "max_budget_usd", 10.0)),
                timeout_seconds=_agent_timeout(
                    "TREND_PREDICTION_AGENT_TIMEOUT_SECONDS",
                    default=param("prediction", "timeout_seconds", 900),
                    minimum=120,
                ),
                sdk_log=sdk_logger,
            ),
            agent_name="trend_prediction",
            validate=lambda d: isinstance(d.get("predictions"), list),
            sdk_log=log_event,
        )
    )

    predictions = payload.get("predictions")
    if not isinstance(predictions, list):
        raise RuntimeError("invalid_trend_prediction_payload")
    # 过滤无效 prediction 而非丢弃全部
    valid_keys = {str(cluster.get("cluster_key")) for cluster in clusters if cluster.get("cluster_key")}
    valid = [p for p in predictions if str(p.get("signal_cluster_key")) in valid_keys][:max_predictions]
    # 时间字段由 Python 确定（模型生成的时间不可信，见 schema 注释）。
    # horizon_days 也一样：实测模型给出过 735/869683 这种值，而窗口是固定的。
    for p in valid:
        p["created_at"] = now_dt.isoformat()
        p["target_start_at"] = now_dt.isoformat()
        p["target_end_at"] = target_end.isoformat()
        p["horizon_days"] = horizon_days
    return valid

# _budget 已抽取到 agent_sdk_runner._budget
