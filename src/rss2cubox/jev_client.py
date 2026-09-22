"""Jev（TypeSafe 系统一模型）客户端 —— 只做结构化判断，不做生成。

POST {JEV_BASE_URL}/v1/systemone：一个 state + 多个命名问题（noul 是非 /
score 评分 / choice 选择），答案带概率分布。无 OpenAI 兼容层。

用法约定：
- JEV_BASE_URL / JEV_API_KEY 同时配置才启用，否则所有调用返回 None，
  调用方直接跳过 —— 不配 key 就是关闭，无需独立开关。
- API 没有用量查询端点，usage 只随响应返回，消耗台账靠 jev_call_done 日志自建
  （字段名与 enrich 的 model_usage 口径对齐）。
- 失败不抛异常：返回 None + WARN 日志。交叉校验类用途宁可没有结果也不该
  阻断主流程。
"""
from __future__ import annotations

import os
from typing import Any

import requests

_TIMEOUT_SECONDS = 20.0


def jev_configured() -> bool:
    return bool(os.getenv("JEV_BASE_URL", "").strip() and os.getenv("JEV_API_KEY", "").strip())


def jev_systemone(
    state: str,
    questions: dict[str, dict[str, Any]],
    *,
    log_event: Any = None,
    doc_id: str = "",
    stage: str = "jev",
) -> dict[str, Any] | None:
    """调用 /v1/systemone，返回完整响应 dict（含 answers/usage/model）。

    未配置、请求失败、非 200 一律返回 None —— 调用方按"没有校验结果"处理。
    """
    if not jev_configured():
        return None
    base = os.getenv("JEV_BASE_URL", "").strip().rstrip("/")
    model = os.getenv("JEV_MODEL", "jev-latest")
    try:
        resp = requests.post(
            f"{base}/v1/systemone",
            json={"model": model, "state": state, "questions": questions},
            headers={"Authorization": f"Bearer {os.getenv('JEV_API_KEY', '').strip()}"},
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as exc:  # noqa: BLE001
        _warn(log_event, doc_id, stage, error=f"{type(exc).__name__}: {str(exc)[:120]}")
        return None
    if resp.status_code != 200:
        _warn(log_event, doc_id, stage, http_status=resp.status_code, error=resp.text[:120])
        return None
    data = resp.json()
    usage = data.get("usage") or {}
    if log_event:
        log_event(
            "INFO",
            "jev_call_done",
            stage=stage,
            doc_id=doc_id,
            model=data.get("model", model),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )
    return data


def _warn(log_event: Any, doc_id: str, stage: str, **fields: Any) -> None:
    if log_event is None:
        return
    log_event("WARN", "jev_call_failed", stage=stage, doc_id=doc_id, **fields)
