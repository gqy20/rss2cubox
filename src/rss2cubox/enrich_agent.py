"""
阶段 1.5 — 全文深化 Agent
对初筛通过（score >= threshold）的条目，使用 Claude Agent SDK + Jina Reader(MCP Tool)
逐条读取原文全文，重新生成更高质量的 hidden_signal / core_event / actionable。
结果直接覆盖 analyses dict，供后续 pipeline 使用。

设计原则：
- 只精读通过粗筛的条目，不处理所有候选，控制时间和成本
- 有限并发（ENRICH_MAX_WORKERS），默认 3
- 单条失败静默回退到原始粗筛结果
- 可通过 ENRICH_AGENT_ENABLED=false 关闭
"""
from __future__ import annotations

import os
from typing import Any

ENRICH_AGENT_ENABLED = os.getenv("ENRICH_AGENT_ENABLED", "true").lower() not in ("false", "0", "no")
ENRICH_MAX_WORKERS = max(1, int(os.getenv("ENRICH_MAX_WORKERS", "3")))
ENRICH_MIN_SCORE = float(os.getenv("ENRICH_MIN_SCORE", "0.7"))  # 只深化高于此分的条目
ENRICH_MAX_ITEMS = int(os.getenv("ENRICH_MAX_ITEMS", "15"))     # 最多深化条数，防止超时
ENRICH_ITEM_TIMEOUT_SECONDS = max(10, int(os.getenv("ENRICH_ITEM_TIMEOUT_SECONDS", "90")))
ENRICH_ALLOW_WEBFETCH_FALLBACK = os.getenv("ENRICH_ALLOW_WEBFETCH_FALLBACK", "false").lower() in ("1", "true", "yes")
JINA_READER_BASE = os.getenv("JINA_READER_BASE", "https://r.jina.ai/")
JINA_MAX_CHARS = max(1000, int(os.getenv("JINA_MAX_CHARS", "10000")))
_enrich_max_budget_raw = os.getenv("ENRICH_MAX_BUDGET_USD", "0.03").strip()
try:
    ENRICH_MAX_BUDGET_USD = float(_enrich_max_budget_raw) if _enrich_max_budget_raw else None
except ValueError:
    ENRICH_MAX_BUDGET_USD = None

SYSTEM_PROMPT = (
    "你是一位顶级科技产业分析师，正在对一篇已通过初筛的高价值文章进行深度精读。\n"
    "你已拥有文章的标题与初步摘要，现在优先通过 read_webpage_jina 工具获取原文全文。\n"
    "阅读完全文后，调用 submit_enriched 工具提交深化后的分析结果。\n"
    "若 read_webpage_jina 失败且系统允许，可改用 WebFetch 作为兜底。\n"
    "要求：\n"
    "- core_event：冷静客观地用一句话描述事实（≤60字）\n"
    "- hidden_signal：这意味着什么？背后的范式转移、行业冲击或深层技术含义（≤100字）\n"
    "- actionable：工程师/独立开发者应如何行动？（≤60字）\n"
    "- score：在原始分基础上，基于全文内容重新评估 0.0-1.0\n"
    "所有输出必须使用简体中文。如果读取网页失败，请基于已有信息尽力输出。"
)


def _build_user_prompt(item: dict, original: dict) -> str:
    return (
        f"文章标题：{item.get('title', '')}\n"
        f"原文链接：{item.get('url', '')}\n"
        f"初步摘要：{item.get('description', '')[:500]}\n"
        f"初步评分：{original.get('score', 0):.2f}\n"
        f"初步核心事件：{original.get('core_event', '')}\n\n"
        "请先调用 read_webpage_jina(url=原文链接) 读取全文，再调用 submit_enriched 提交深化分析。"
    )


async def _enrich_one(item: dict, original: dict) -> dict | None:
    import anyio

    try:
        from claude_agent_sdk import (  # type: ignore
            ClaudeAgentOptions,
            ClaudeSDKClient,
            PermissionResultAllow,
            PermissionResultDeny,
            create_sdk_mcp_server,
            tool,
        )
    except ImportError:
        return None

    result_holder: dict[str, Any] = {}
    expected_url = str(item.get("url", "")).strip()
    if not expected_url:
        return None

    @tool(
        "read_webpage_jina",
        "通过 Jina Reader 获取文章原文完整内容（Markdown），用于深度阅读",
        {"url": str},
    )
    async def read_webpage_jina(args: dict) -> dict:
        url = str(args.get("url", "")).strip()
        if not url:
            return {"content": [{"type": "text", "text": "missing url"}], "is_error": True}
        if url != expected_url:
            return {"content": [{"type": "text", "text": f"url_not_allowed: {url}"}], "is_error": True}

        def _fetch() -> tuple[bool, str]:
            import requests
            try:
                resp = requests.get(
                    f"{JINA_READER_BASE}{url}",
                    headers={"Accept": "text/plain", "x-respond-with": "markdown"},
                    timeout=20,
                )
                resp.raise_for_status()
                return True, resp.text[:JINA_MAX_CHARS]
            except Exception as e:
                return False, f"jina_fetch_failed: {e}"

        ok, payload = await anyio.to_thread.run_sync(_fetch)
        if not ok:
            return {"content": [{"type": "text", "text": payload}], "is_error": True}
        return {"content": [{"type": "text", "text": payload}]}

    @tool(
        "submit_enriched",
        "提交基于全文精读后的深化分析结果",
        {"core_event": str, "hidden_signal": str, "actionable": str, "score": float},
    )
    async def submit_enriched(args: dict) -> dict:
        result_holder.update(args)
        return {"content": [{"type": "text", "text": "深化分析已收到。"}]}

    server = create_sdk_mcp_server(
        name="enrich-tools",
        version="1.0.0",
        tools=[read_webpage_jina, submit_enriched],
    )

    async def can_use_tool(tool_name: str, tool_input: dict[str, Any], _ctx: Any) -> Any:
        if tool_name != "WebFetch":
            return PermissionResultAllow()
        if not ENRICH_ALLOW_WEBFETCH_FALLBACK:
            return PermissionResultDeny(message="WebFetch fallback disabled")
        requested = str(tool_input.get("url", "")).strip() if isinstance(tool_input, dict) else ""
        if requested == expected_url:
            return PermissionResultAllow()
        return PermissionResultDeny(
            message=f"只允许抓取当前文章 URL。expected={expected_url}, got={requested}",
        )

    allowed_tools = [
        "mcp__enrich-tools__read_webpage_jina",
        "mcp__enrich-tools__submit_enriched",
    ]
    if ENRICH_ALLOW_WEBFETCH_FALLBACK:
        allowed_tools.append("WebFetch")

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        allowed_tools=allowed_tools,
        mcp_servers={"enrich-tools": server},
        permission_mode="acceptEdits",
        max_turns=8,  # Jina 读取 + 可选兜底 + submit_enriched
        max_budget_usd=ENRICH_MAX_BUDGET_USD,
        can_use_tool=can_use_tool,
    )

    async with ClaudeSDKClient(options=options) as client:
        with anyio.fail_after(ENRICH_ITEM_TIMEOUT_SECONDS):
            await client.query(_build_user_prompt(item, original))
            async for _ in client.receive_response():
                pass

    return result_holder if result_holder else None


async def _enrich_all(
    items_to_enrich: list[tuple[dict, dict]],
    analyses: dict[str, dict],
    log_event: Any,
) -> None:
    import anyio

    semaphore = anyio.Semaphore(ENRICH_MAX_WORKERS)

    async def run_one(item: dict, original: dict) -> None:
        eid = item["eid"]
        async with semaphore:
            try:
                enriched = await _enrich_one(item, original)
                if enriched:
                    # 合并：保留原始字段，覆盖深化后的核心字段
                    merged = {**original}
                    for key in ("core_event", "hidden_signal", "actionable"):
                        val = str(enriched.get(key, "")).strip()
                        if val:
                            merged[key] = val
                    try:
                        new_score = float(enriched.get("score", original.get("score", 0)))
                        merged["score"] = max(0.0, min(1.0, new_score))
                    except (TypeError, ValueError):
                        pass
                    merged["enriched"] = True
                    analyses[eid] = merged
                    log_event("INFO", "enrich_done", stage="enrich", eid=eid,
                              score=merged.get("score"), hidden_signal=merged.get("hidden_signal", "")[:40])
            except Exception as e:
                log_event("WARN", "enrich_failed", stage="enrich", eid=eid, error=str(e))

    async with anyio.create_task_group() as tg:
        for item, original in items_to_enrich:
            tg.start_soon(run_one, item, original)


def run_enrich_analysis(
    *,
    candidates: list[dict],
    analyses: dict[str, dict],
    ai_min_score: float | None = None,
    log_event: Any,
) -> None:
    """
    对 analyses 中 score >= ENRICH_MIN_SCORE 的条目进行全文深化，
    结果直接更新 analyses dict（原地修改）。
    """
    if not ENRICH_AGENT_ENABLED:
        log_event("INFO", "enrich_skipped", stage="enrich", reason="ENRICH_AGENT_ENABLED=false")
        return

    threshold = ai_min_score if ai_min_score is not None else ENRICH_MIN_SCORE

    # 筛选需要深化的条目，按 score 降序，取前 ENRICH_MAX_ITEMS 条
    to_enrich: list[tuple[dict, dict]] = []
    for c in candidates:
        eid = c.get("eid", "")
        analysis = analyses.get(eid)
        if not analysis:
            continue
        score = analysis.get("score", 0)
        if score >= threshold:
            to_enrich.append((c, analysis))

    to_enrich.sort(key=lambda x: -x[1].get("score", 0))
    to_enrich = to_enrich[:ENRICH_MAX_ITEMS]

    if not to_enrich:
        log_event("INFO", "enrich_skipped", stage="enrich", reason="no_eligible_items")
        return

    log_event("INFO", "enrich_start", stage="enrich", count=len(to_enrich),
              max_workers=ENRICH_MAX_WORKERS)

    try:
        import anyio
        anyio.run(_enrich_all, to_enrich, analyses, log_event)
        log_event("INFO", "enrich_complete", stage="enrich",
                  enriched=sum(1 for a in analyses.values() if a.get("enriched")))
    except Exception as e:
        log_event("WARN", "enrich_error", stage="enrich", error=str(e))
