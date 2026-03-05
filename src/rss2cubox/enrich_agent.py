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

import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

ENRICH_AGENT_ENABLED = os.getenv("ENRICH_AGENT_ENABLED", "true").lower() not in ("false", "0", "no")
ENRICH_MAX_WORKERS = max(1, int(os.getenv("ENRICH_MAX_WORKERS", "10")))
ENRICH_MIN_SCORE = float(os.getenv("ENRICH_MIN_SCORE", "0.7"))
ENRICH_MAX_ITEMS = int(os.getenv("ENRICH_MAX_ITEMS", "15"))
ENRICH_ITEM_TIMEOUT_SECONDS = max(10, int(os.getenv("ENRICH_ITEM_TIMEOUT_SECONDS", "90")))
ENRICH_ENABLE_SKILLS = os.getenv("ENRICH_ENABLE_SKILLS", "true").lower() in ("1", "true", "yes")
JINA_READER_BASE = os.getenv("JINA_READER_BASE", "https://r.jina.ai/")
JINA_MAX_CHARS = max(1000, int(os.getenv("JINA_MAX_CHARS", "10000")))
_enrich_max_budget_raw = os.getenv("ENRICH_MAX_BUDGET_USD", "0.03").strip()
try:
    ENRICH_MAX_BUDGET_USD = float(_enrich_max_budget_raw) if _enrich_max_budget_raw else None
except ValueError:
    ENRICH_MAX_BUDGET_USD = None


class EnrichedResult(BaseModel):
    core_event: str = ""
    hidden_signal: str = ""
    actionable: str = ""
    score: float = 0.0

    @field_validator("score", mode="before")
    @classmethod
    def _coerce_score(cls, v: Any) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0


SYSTEM_PROMPT = (
    "你是一位顶级科技产业分析师，正在对一篇已通过初筛的高价值文章进行深度精读。\n"
    "你已拥有文章的标题与初步摘要，现在优先通过 read_webpage_jina 工具获取原文全文。\n"
    "阅读完毕后，直接以 JSON 格式输出分析结果（不要调用任何提交工具）：\n"
    "字段要求：\n"
    "- core_event：冷静客观地用一句话描述事实（≤60字）\n"
    "- hidden_signal：这意味着什么？背后的范式转移、行业冲击或深层技术含义（≤100字）\n"
    "- actionable：工程师/独立开发者应如何行动？（≤60字）\n"
    "- score：在原始分基础上，基于全文内容重新评估 0.0-1.0\n"
    "所有输出必须使用简体中文。如果读取网页失败，请基于已有标题和摘要尽力输出。"
)


def _build_user_prompt(item: dict, original: dict) -> str:
    return (
        f"文章标题：{item.get('title', '')}\n"
        f"原文链接：{item.get('url', '')}\n"
        f"初步摘要：{item.get('description', '')[:500]}\n"
        f"初步评分：{original.get('score', 0):.2f}\n"
        f"初步核心事件：{original.get('core_event', '')}\n\n"
        "步骤：\n"
        "1. 调用 read_webpage_jina 读取原文（传入上方原文链接）。\n"
        "2. 无论读取是否成功，直接以 JSON 格式输出分析结果，包含：\n"
        "   core_event、hidden_signal、actionable、score 四个字段。\n"
        "   如果读取失败，基于已有标题、摘要和初步分析直接输出 JSON。"
    )


def _extract_json_from_text(text: str) -> dict | None:
    """从文本中提取 JSON 对象"""
    if not text:
        return None

    # 优先匹配 JSON 代码块
    json_block_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_block_match:
        try:
            return json.loads(json_block_match.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试匹配裸 JSON 对象
    json_match = re.search(r"(\{[\s\S]*\})", text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    return None


async def _enrich_one(item: dict, original: dict) -> tuple[dict | None, str]:
    import anyio

    try:
        from claude_agent_sdk import (  # type: ignore
            AssistantMessage,
            ClaudeAgentOptions,
            TextBlock,
            ToolUseBlock,
            create_sdk_mcp_server,
            query,
            tool,
        )
    except ImportError:
        return None, "claude_agent_sdk_import_error"

    expected_url = str(item.get("url", "")).strip()
    if not expected_url:
        return None, "missing_url"

    @tool(
        "read_webpage_jina",
        "通过 Jina Reader 获取文章原文完整内容（Markdown），用于深度阅读",
        {"url": str},
    )
    async def read_webpage_jina(args: dict) -> dict:
        def _fetch() -> tuple[bool, str]:
            import requests
            try:
                resp = requests.get(
                    f"{JINA_READER_BASE}{expected_url}",
                    headers={"Accept": "text/plain", "x-respond-with": "markdown"},
                    timeout=20,
                )
                resp.raise_for_status()
                return True, resp.text[:JINA_MAX_CHARS]
            except Exception as e:
                return False, f"jina_fetch_failed: {e}"

        ok, payload = await anyio.to_thread.run_sync(_fetch)
        return {"content": [{"type": "text", "text": payload if ok else f"[网页读取失败，请基于已有标题和摘要完成分析] {payload}"}]}

    server = create_sdk_mcp_server(
        name="enrich-tools",
        version="1.0.0",
        tools=[read_webpage_jina],
    )

    allowed_tools = ["mcp__enrich-tools__read_webpage_jina"]
    if ENRICH_ENABLE_SKILLS:
        allowed_tools.append("Skill")

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        allowed_tools=allowed_tools,
        mcp_servers={"enrich-tools": server},
        permission_mode="acceptEdits",
        max_turns=6,
        max_budget_usd=ENRICH_MAX_BUDGET_USD,
        cwd=Path.cwd(),
        setting_sources=["project"] if ENRICH_ENABLE_SKILLS else None,
    )

    full_response: list[str] = []

    try:
        with anyio.fail_after(ENRICH_ITEM_TIMEOUT_SECONDS):
            async for message in query(prompt=_build_user_prompt(item, original), options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock):
                            print(f"[enrich_agent] eid={item.get('eid', '')[:8]} tool_use: {block.name}", flush=True)
                        elif isinstance(block, TextBlock):
                            full_response.append(block.text or "")
    except Exception as e:
        print(f"[enrich_agent] eid={item.get('eid', '')[:8]} query_error: {e}", flush=True)

    # 解析 JSON 结果并用 pydantic 校验
    if full_response:
        full_text = "\n".join(full_response)
        parsed = _extract_json_from_text(full_text)
        if parsed:
            try:
                validated = EnrichedResult.model_validate(parsed)
                result = validated.model_dump()
                if result.get("core_event") or result.get("hidden_signal"):
                    print(f"[enrich_agent] eid={item.get('eid', '')[:8]} validated: ok", flush=True)
                    return result, "ok"
            except Exception as e:
                print(f"[enrich_agent] eid={item.get('eid', '')[:8]} validation_error: {e}", flush=True)

    print(f"[enrich_agent] eid={item.get('eid', '')[:8]} parse_failed: no_valid_json", flush=True)
    return None, "parse_failed"


async def _enrich_all(
    items_to_enrich: list[tuple[dict, dict]],
    analyses: dict[str, dict],
    log_event: Any,
) -> dict[str, int]:
    import anyio

    semaphore = anyio.Semaphore(ENRICH_MAX_WORKERS)
    stats = {"started": 0, "succeeded": 0, "failed": 0, "empty": 0}

    async def run_one(item: dict, original: dict) -> None:
        eid = item["eid"]
        async with semaphore:
            stats["started"] += 1
            log_event(
                "INFO",
                "enrich_item_start",
                stage="enrich",
                eid=eid,
                url=str(item.get("url", "")).strip(),
                score=original.get("score", 0),
            )
            try:
                enriched, reason = await _enrich_one(item, original)
                if enriched:
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
                    stats["succeeded"] += 1
                    log_event("INFO", "enrich_done", stage="enrich", eid=eid,
                              score=merged.get("score"), hidden_signal=merged.get("hidden_signal", "")[:40])
                else:
                    stats["empty"] += 1
                    log_event("WARN", "enrich_failed", stage="enrich", eid=eid, error=f"no_result:{reason}")
            except Exception as e:
                stats["failed"] += 1
                log_event("WARN", "enrich_failed", stage="enrich", eid=eid, error=str(e))

    async with anyio.create_task_group() as tg:
        for item, original in items_to_enrich:
            tg.start_soon(run_one, item, original)
    return stats


def run_enrich_analysis(
    *,
    candidates: list[dict],
    analyses: dict[str, dict],
    ai_min_score: float | None = None,
    log_event: Any,
) -> None:
    """对 analyses 中 score >= ENRICH_MIN_SCORE 的条目进行全文深化，结果直接更新 analyses dict。"""
    if not ENRICH_AGENT_ENABLED:
        log_event("INFO", "enrich_skipped", stage="enrich", reason="ENRICH_AGENT_ENABLED=false")
        return

    threshold = ai_min_score if ai_min_score is not None else ENRICH_MIN_SCORE

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

    log_event("INFO", "enrich_start", stage="enrich", count=len(to_enrich), max_workers=ENRICH_MAX_WORKERS)

    try:
        import anyio
        enrich_stats = anyio.run(_enrich_all, to_enrich, analyses, log_event)
        log_event("INFO", "enrich_complete", stage="enrich",
                  enriched=enrich_stats.get("succeeded", 0),
                  failed=enrich_stats.get("failed", 0),
                  empty=enrich_stats.get("empty", 0),
                  started=enrich_stats.get("started", len(to_enrich)))
    except Exception as e:
        log_event("WARN", "enrich_error", stage="enrich", error=str(e))
