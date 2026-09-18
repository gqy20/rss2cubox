"""政策预筛（triage）Agent。

存在的理由：deep enrich 每篇一次 LLM 调用（实测 ~$0.14/篇，CLI 记账值），
而政策源里混着大量与 AI 无关的民生通知（停水、月票、招考、活动报道）。
全量 deep enrich 442 篇约 $62，其中真正相关的可能只有几十篇。

预筛把 N 个标题打包进一次调用，只做"是否政策文件 + AI 相关度"两个判断，
不抽详细字段。一次调用 ~50 个标题，成本约为逐篇的 1/50。
"""
from __future__ import annotations

import json
import os
from functools import partial
from typing import Any

import anyio

from rss2cubox.agent_sdk_runner import (
    _agent_timeout,
    _budget,
    make_sdk_logger,
    run_json_agent,
    run_with_fallback,
)
from rss2cubox.prompt_registry import get, param

# system_prompt / 输出 schema / user 静态指令集中在项目根 prompts/policy_triage.yaml：
# 修改判定标准只动 yml，下次运行生效，日志带 prompt_version 便于追溯。
# 运行参数优先级：.env 环境变量 > yml params > 代码默认值（param 负责解析）。
_PROMPT = get("policy_triage")

# 每批标题数。实测：10 条稳定成功；20 条偏激进（多次出现
# error_max_structured_output_retries）；50 条直接撞满超时。
TRIAGE_BATCH_SIZE = param("policy_triage", "batch_size", 10, env_var="POLICY_TRIAGE_BATCH_SIZE", minimum=1)

SYSTEM_PROMPT = _PROMPT.system_prompt
TRIAGE_OUTPUT_SCHEMA: dict[str, Any] = _PROMPT.output_schema


def _build_prompt(batch: list[dict[str, Any]]) -> str:
    slim = [
        {
            "id": str(doc.get("id", "")),
            "title": str(doc.get("title", ""))[:200],
            "region": str(doc.get("region", "")),
            "level": str(doc.get("level", "")),
            "site_name": str(doc.get("site_name", ""))[:40],
        }
        for doc in batch
    ]
    return json.dumps(
        {
            "count": len(slim),
            "items": slim,
            "instructions": _PROMPT.instructions_list,
        },
        ensure_ascii=False,
    )


async def _triage_batch(
    batch: list[dict[str, Any]],
    log_event: Any | None = None,
) -> tuple[list[dict[str, Any]], str]:
    valid_ids = {str(doc.get("id", "")) for doc in batch}
    sdk_logger = make_sdk_logger("policy_triage", log_event=log_event, batch_size=len(batch), prompt_version=_PROMPT.version)

    def _fail(reason: str) -> tuple[list[dict[str, Any]], str]:
        # 失败必须打日志：否则整批静默返回空，只能从 uncovered 反推出事了
        if log_event:
            log_event(
                "WARN",
                "policy_triage_batch_failed",
                stage="policy_triage",
                batch_size=len(batch),
                reason=reason,
            )
        return [], reason

    try:
        payload = await run_with_fallback(
            partial(
                run_json_agent,
                prompt=_build_prompt(batch),
                system_prompt=SYSTEM_PROMPT,
                schema=TRIAGE_OUTPUT_SCHEMA,
                allowed_tools=[],
                mcp_servers=None,
                max_turns=param("policy_triage", "max_turns", 10),
                max_budget_usd=_budget("POLICY_TRIAGE_MAX_BUDGET_USD", param("policy_triage", "max_budget_usd", 2.0)),
                timeout_seconds=_agent_timeout(
                    "POLICY_TRIAGE_TIMEOUT_SECONDS",
                    default=param("policy_triage", "timeout_seconds", 240),
                    minimum=90,
                ),
                setting_sources=None,
                sdk_log=sdk_logger,
            ),
            agent_name="policy_triage",
            validate=lambda d: isinstance(d.get("results"), list) and len(d["results"]) > 0,
            sdk_log=log_event,
        )
    except TimeoutError:
        return _fail("timeout")
    except Exception as exc:  # noqa: BLE001
        return _fail(f"{type(exc).__name__}: {str(exc)[:200]}")

    raw = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return _fail("invalid_payload")

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    hallucinated = 0
    for row in raw:
        if not isinstance(row, dict):
            continue
        doc_id = str(row.get("id", "")).strip()
        # 只接受输入里真实存在的 id，防止模型编造或串行
        if doc_id not in valid_ids or doc_id in seen:
            hallucinated += 1
            continue
        seen.add(doc_id)
        relevance = row.get("ai_relevance")
        out.append(
            {
                "id": doc_id,
                "is_policy": bool(row.get("is_policy")),
                "ai_relevance": int(relevance) if isinstance(relevance, int) and 1 <= relevance <= 5 else 1,
                "reason": str(row.get("reason", ""))[:120],
            }
        )

    missing = len(valid_ids) - len(out)
    reason = "ok"
    if missing > 0 or hallucinated > 0:
        reason = f"partial: missing={missing} hallucinated={hallucinated}"
    if log_event:
        log_event(
            "INFO" if missing == 0 else "WARN",
            "policy_triage_batch_done",
            stage="policy_triage",
            batch_size=len(batch),
            returned=len(out),
            missing=missing,
            hallucinated=hallucinated,
        )
    return out, reason


async def _triage_all(
    batches: list[list[dict[str, Any]]],
    log_event: Any | None,
    *,
    max_concurrent: int,
    on_batch_done: Any | None = None,
) -> list[dict[str, Any]]:
    semaphore = anyio.Semaphore(max(1, max_concurrent))
    collected: list[list[dict[str, Any]]] = []

    async def run_one(batch: list[dict[str, Any]]) -> None:
        async with semaphore:
            rows, _reason = await _triage_batch(batch, log_event)
            collected.append(rows)
            # 每批跑完就落库，不等全部批次。442 篇要跑 ~10 分钟 / 45 批，
            # 全部收集完再一次性写的话，中断就全部重来。
            # 回调做的是阻塞 DB IO，放到线程里跑；异常不能影响其他批次。
            if on_batch_done is not None and rows:
                try:
                    await anyio.to_thread.run_sync(on_batch_done, rows)
                except Exception as exc:  # noqa: BLE001
                    if log_event:
                        log_event(
                            "WARN",
                            "policy_triage_flush_failed",
                            stage="policy_triage",
                            rows=len(rows),
                            error=f"{type(exc).__name__}: {str(exc)[:160]}",
                        )

    async with anyio.create_task_group() as tg:
        for batch in batches:
            tg.start_soon(run_one, batch)

    return [row for group in collected for row in group]


def triage_policy_documents(
    docs: list[dict[str, Any]],
    *,
    batch_size: int | None = None,
    max_concurrent: int | None = None,
    log_event: Any | None = None,
    on_batch_done: Any | None = None,
) -> dict[str, Any]:
    """对一批文档标题做预筛，返回 {results, stats}。

    on_batch_done(rows) 在每批完成后被调用（工作线程里），用于增量落库。
    """
    if not docs:
        return {"results": [], "stats": {"input": 0, "triaged": 0, "batches": 0, "policy": 0, "relevant": 0}}

    size = batch_size or TRIAGE_BATCH_SIZE
    concurrent = max_concurrent or param("policy_triage", "max_concurrent", 3, env_var="POLICY_TRIAGE_MAX_CONCURRENT", minimum=1)
    batches = [docs[i : i + size] for i in range(0, len(docs), size)]

    if log_event:
        log_event(
            "INFO",
            "policy_triage_start",
            stage="policy_triage",
            count=len(docs),
            batches=len(batches),
            batch_size=size,
            max_concurrent=concurrent,
        )

    results = anyio.run(
        partial(_triage_all, batches, log_event, max_concurrent=concurrent, on_batch_done=on_batch_done)
    )

    threshold = param("policy_enrich", "min_relevance", 3, env_var="POLICY_ENRICH_MIN_RELEVANCE", minimum=1)
    stats = {
        "input": len(docs),
        "triaged": len(results),
        "batches": len(batches),
        "policy": sum(1 for r in results if r["is_policy"]),
        "relevant": sum(1 for r in results if r["is_policy"] and r["ai_relevance"] >= threshold),
        "threshold": threshold,
        "uncovered": len(docs) - len(results),
    }
    if log_event:
        log_event("INFO", "policy_triage_done", stage="policy_triage", **stats)
    return {"results": results, "stats": stats}
