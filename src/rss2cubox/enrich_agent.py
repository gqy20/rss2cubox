"""
阶段 1.5 — 全文深化 Agent
对初筛通过（score >= threshold）的条目，使用 Claude Agent SDK + Jina Reader(MCP Tool)
逐条读取原文全文，重新生成更高质量的 hidden_signal / core_event / actionable。
结果直接覆盖 analyses dict，供后续 pipeline 使用。

设计原则：
- 只精读通过粗筛的条目，不处理所有候选，控制时间和成本
- 有限并发（ENRICH_MAX_WORKERS），默认 10
- 使用 output_format 让 CLI 自动验证 JSON Schema（内置重试）
- 应用层仅对 timeout/网络错误重试（ENRICH_APP_MAX_RETRIES）
- 单条失败静默回退到原始粗筛结果
- 可通过 ENRICH_AGENT_ENABLED=false 关闭
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

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
# 应用层重试配置（仅针对 timeout/网络错误）
ENRICH_APP_MAX_RETRIES = int(os.getenv("ENRICH_APP_MAX_RETRIES", "2"))
ENRICH_RETRY_DELAY_BASE = float(os.getenv("ENRICH_RETRY_DELAY_BASE", "1.0"))

# JSON Schema 用于 output_format（CLI 层自动验证）
ENRICH_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "core_event": {"type": "string", "maxLength": 100},
        "hidden_signal": {"type": "string", "maxLength": 200},
        "actionable": {"type": "string", "maxLength": 100},
        "score": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["core_event", "hidden_signal", "actionable", "score"],
}


SYSTEM_PROMPT = (
    "你是一位顶级科技产业分析师，正在对一篇已通过初筛的高价值文章进行深度精读。\n"
    "你已拥有文章的标题与初步摘要，现在优先通过 read_webpage_jina 工具获取原文全文。\n"
    "阅读完毕后，直接以 JSON 格式输出分析结果。\n"
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
        "2. 无论读取是否成功，直接输出 JSON 格式的分析结果。\n"
        "   如果读取失败，基于已有标题、摘要和初步分析输出 JSON。"
    )


def _extract_json_from_text(text: str) -> dict | None:
    """从文本中提取 JSON 对象（回退解析用）"""
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


def _make_stderr_logger(prefix: str, limit: int = 40) -> tuple[list[str], Any]:
    lines: list[str] = []

    def _log(line: str) -> None:
        text = str(line).strip()
        if not text:
            return
        lines.append(text)
        if len(lines) > limit:
            del lines[: len(lines) - limit]
        print(f"[{prefix}] cli_stderr: {text}", flush=True)

    return lines, _log


def _has_enrich_content(payload: dict[str, Any] | None) -> bool:
    return bool(payload and (payload.get("core_event") or payload.get("hidden_signal")))


async def _enrich_one(item: dict, original: dict) -> tuple[dict | None, str]:
    """
    使用 output_format 让 CLI 处理 JSON Schema 验证和重试。
    应用层仅对 timeout/网络错误进行有限重试。
    """
    import anyio

    try:
        from claude_agent_sdk import (  # type: ignore
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
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

    eid_short = item.get("eid", "")[:8]
    stderr_lines, stderr_logger = _make_stderr_logger(f"enrich_agent:{eid_short}")

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        allowed_tools=allowed_tools,
        mcp_servers={"enrich-tools": server},
        permission_mode="acceptEdits",
        max_turns=6,
        max_budget_usd=ENRICH_MAX_BUDGET_USD,
        cwd=Path.cwd(),
        setting_sources=["project"] if ENRICH_ENABLE_SKILLS else None,
        stderr=stderr_logger,
        # 使用 output_format 让 CLI 自动验证 JSON Schema（CLI 内置重试）
        output_format={"type": "json_schema", "schema": ENRICH_OUTPUT_SCHEMA},
    )

    last_error = "no_result"

    # 应用层重试：仅针对 timeout 和网络错误
    for attempt in range(ENRICH_APP_MAX_RETRIES + 1):
        final_result: dict[str, Any] | None = None
        result_text: str | None = None
        assistant_chunks: list[str] = []
        try:
            with anyio.fail_after(ENRICH_ITEM_TIMEOUT_SECONDS):
                async for message in query(prompt=_build_user_prompt(item, original), options=options):
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock) and block.text:
                                assistant_chunks.append(block.text)
                    elif isinstance(message, ResultMessage):
                        # CLI 层 JSON Schema 验证成功
                        if message.structured_output:
                            result = message.structured_output
                            if _has_enrich_content(result):
                                final_result = result
                                last_error = "ok"
                            else:
                                last_error = "empty_fields"
                        elif message.subtype == "error_max_budget_usd":
                            last_error = "error_max_budget_usd"
                        # CLI 层重试耗尽
                        elif message.subtype == "error_max_structured_output_retries":
                            last_error = "cli_retry_exhausted"
                        # 其他错误
                        elif message.is_error:
                            last_error = f"subtype:{message.subtype}"
                            print(f"[enrich_agent] eid={eid_short} error: subtype={message.subtype}", flush=True)
                        # structured_output 为空但有 result，尝试手动解析 JSON
                        elif message.result:
                            result_text = message.result
                            parsed = _extract_json_from_text(message.result)
                            if _has_enrich_content(parsed):
                                final_result = parsed
                                last_error = "ok"
                            else:
                                last_error = "no_structured_output"
                                print(f"[enrich_agent] eid={eid_short} no_structured_output, result preview: {message.result[:200] if message.result else 'None'}", flush=True)
                        elif message.subtype and message.subtype not in ("success", "completed_end_turn"):
                            last_error = f"subtype:{message.subtype}"
                            print(f"[enrich_agent] eid={eid_short} no_structured_output: subtype={message.subtype}", flush=True)
                        else:
                            last_error = "no_structured_output"
                            print(f"[enrich_agent] eid={eid_short} no_structured_output: subtype={message.subtype}", flush=True)
        except TimeoutError:
            last_error = "timeout"
            # timeout 可以重试
        except Exception as e:
            last_error = f"error:{type(e).__name__}:{e}"
            if stderr_lines:
                print(f"[enrich_agent] eid={eid_short} recent_cli_stderr: {' | '.join(stderr_lines[-5:])}", flush=True)
            # 某些网络错误可以重试

        if final_result:
            print(f"[enrich_agent] eid={eid_short} validated: ok", flush=True)
            return final_result, "ok"
        if assistant_chunks:
            parsed = _extract_json_from_text("\n".join(assistant_chunks))
            if _has_enrich_content(parsed):
                print(f"[enrich_agent] eid={eid_short} parsed_from_assistant: ok", flush=True)
                return parsed, "ok"
        if result_text:
            parsed = _extract_json_from_text(result_text)
            if _has_enrich_content(parsed):
                print(f"[enrich_agent] eid={eid_short} parsed_from_result: ok", flush=True)
                return parsed, "ok"

        # 指数退避重试（最后一次不等待）
        if attempt < ENRICH_APP_MAX_RETRIES and (
            last_error == "timeout"
            or last_error.startswith("error:ConnectionError")
            or last_error.startswith("error:HTTPError")
            or last_error.startswith("error:RuntimeError:Attempted to exit a cancel scope")
        ):
            delay = ENRICH_RETRY_DELAY_BASE * (2 ** attempt)
            print(f"[enrich_agent] eid={eid_short} retry {attempt + 1}, wait {delay}s, reason={last_error}", flush=True)
            await anyio.sleep(delay)
        else:
            # 其他错误不重试
            break

    print(f"[enrich_agent] eid={eid_short} failed: {last_error}", flush=True)
    return None, last_error


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
