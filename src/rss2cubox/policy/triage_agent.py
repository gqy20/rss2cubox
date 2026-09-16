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

# 每批标题数。实测：10 条稳定成功；20 条偏激进（多次出现
# error_max_structured_output_retries）；50 条直接撞满超时。
TRIAGE_BATCH_SIZE = max(1, int(os.getenv("POLICY_TRIAGE_BATCH_SIZE", "10")))

TRIAGE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "必须原样回填输入的 id"},
                    "is_policy": {
                        "type": "boolean",
                        "description": "是否为真正的政策/法规/规章/标准/规划文件",
                    },
                    "ai_relevance": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "description": "与 AI/智能体的相关度，标准同 deep enrich",
                    },
                    "reason": {"type": "string", "description": "≤20 字的判定依据（可选）"},
                },
                # reason 故意不列入 required：它是调试用的，一旦要求必填，
                # 模型漏一个就会让整批 schema 校验失败并重试至死，
                # 实测表现为 error_max_structured_output_retries、整批 20 条全丢。
                "required": ["id", "is_policy", "ai_relevance"],
            },
        },
    },
    "required": ["results"],
}


SYSTEM_PROMPT = (
    "你是中国政策情报的预筛员。任务是对一批政策类网站的条目**标题**做快速分类，"
    "决定哪些值得进入后续的深度结构化抽取。你只看标题，不追求精确，追求便宜且不漏。\n"
    "\n"
    "【is_policy 判定】\n"
    "true：法律/行政法规/部门规章/地方性法规/地方政府规章/规范性文件/指导意见/"
    "征求意见稿/技术标准/规划/实施方案/管理办法，以及它们的解读、废止、修订、批复。\n"
    "false：民生服务通知（停水停电、公交月票、招考报名、场馆开放、活动打卡）、"
    "人事任免、会议报道、领导活动、统计数据发布、工作报告、节日慰问、招商引资签约。\n"
    "\n"
    "【ai_relevance 评分标准】与深度抽取阶段保持完全一致：\n"
    "5 = 直接规制 AI/算法/大模型/智能体本身（生成式AI服务、算法推荐、深度合成、"
    "AI安全标准、大模型备案、人工智能产业条例）\n"
    "4 = 不点名 AI 但直接约束 AI 系统必然涉及的对象（数据跨境、个人信息处理、"
    "自动化决策、训练数据、算力、数据要素）\n"
    "3 = 行业性政策，AI 是其中一个受影响方向（金融/医疗/交通/教育/制造的数字化智能化条款）\n"
    "2 = 泛数字经济、科技创新政策，与 AI 间接相关\n"
    "1 = 与 AI 基本无关\n"
    "\n"
    "【重要】\n"
    "- 标题信息不足以判断时，宁可给低分也不要给高分；但 is_policy 存疑时倾向 true，"
    "因为漏掉一份真政策的代价高于多抽一篇。\n"
    "- reason 可选，写的话要简短具体，指出标题里哪个词决定了你的判断。\n"
    "- 但必须为输入里的**每一个** id 都返回一条结果，id 原样回填，"
    "不得改写、不得遗漏、不得新增。\n"
    "\n"
    "只输出符合 JSON Schema 的结构化结果。"
)


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
            "instructions": [
                "为每一个 id 返回一条结果，id 原样回填。",
                "只依据标题判断，不要推测标题之外的内容。",
                "ai_relevance 用 1-5 的整数。",
            ],
        },
        ensure_ascii=False,
    )


async def _triage_batch(
    batch: list[dict[str, Any]],
    log_event: Any | None = None,
) -> tuple[list[dict[str, Any]], str]:
    valid_ids = {str(doc.get("id", "")) for doc in batch}
    sdk_logger = make_sdk_logger("policy_triage", log_event=log_event, batch_size=len(batch))

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
                max_turns=10,
                max_budget_usd=_budget("POLICY_TRIAGE_MAX_BUDGET_USD", 2.0),
                timeout_seconds=_agent_timeout("POLICY_TRIAGE_TIMEOUT_SECONDS", default=240, minimum=90),
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
    concurrent = max_concurrent or max(1, int(os.getenv("POLICY_TRIAGE_MAX_CONCURRENT", "3")))
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

    threshold = max(1, int(os.getenv("POLICY_ENRICH_MIN_RELEVANCE", "3")))
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
