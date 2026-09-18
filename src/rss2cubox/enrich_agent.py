"""
阶段 1.5 — 全文深化 Agent
对候选条目使用 Claude Agent SDK + Jina Reader(MCP Tool)
逐条读取原文全文，重新生成更高质量的 hidden_signal / core_event / actionable。
结果直接覆盖 analyses dict，供后续 pipeline 使用。

设计原则：
- 只精读通过粗筛的条目，不处理所有候选，控制时间和成本
- 有限并发（ENRICH_MAX_WORKERS），默认 10
- 使用 output_format 让 CLI 自动验证 JSON Schema（内置 5 次重试）
- TimeoutError 时按配置退避重试（ENRICH_MAX_RETRIES），其他异常不重试
- 重试用递减超时（首次已接近完成，重试应更快）
- 可通过 ENRICH_AGENT_ENABLED=false 关闭
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from rss2cubox.agent_sdk_runner import get_jina_config, make_sdk_logger, make_stderr_logger, run_json_agent
from rss2cubox.prompt_registry import get, param
from rss2cubox.webpage_reader import read_webpage_text

# 加载 .env 文件（本地开发时 .env 优先级最高，覆盖系统环境变量）
load_dotenv(override=True)

# ENABLED / ENABLE_SKILLS 是部署开关（env-only）；数值型运行参数走
# param 三层解析：.env 环境变量 > prompts/enrich.yaml params > 代码默认值。
ENRICH_AGENT_ENABLED = os.getenv("ENRICH_AGENT_ENABLED", "true").lower() not in ("false", "0", "no")
ENRICH_ENABLE_SKILLS = os.getenv("ENRICH_ENABLE_SKILLS", "true").lower() in ("1", "true", "yes")
ENRICH_MAX_WORKERS = param("enrich", "max_workers", 10, env_var="ENRICH_MAX_WORKERS", minimum=1)
ENRICH_ITEM_TIMEOUT_SECONDS = param("enrich", "item_timeout_seconds", 120, env_var="ENRICH_ITEM_TIMEOUT_SECONDS", minimum=10)
ENRICH_MAX_RETRIES = param("enrich", "max_retries", 1, env_var="ENRICH_MAX_RETRIES", minimum=0)
ENRICH_RETRY_BACKOFF_SECONDS = param("enrich", "retry_backoff_seconds", 30.0, env_var="ENRICH_RETRY_BACKOFF_SECONDS", minimum=1)
# JINA 常量已迁移到 get_jina_config()，在 _enrich_one 中按需调用
ENRICH_MAX_BUDGET_USD = param("enrich", "max_budget_usd", 15.0, env_var="ENRICH_MAX_BUDGET_USD")

# JSON Schema 与 system_prompt 集中在项目根 prompts/enrich.yaml，
# 修改字段定义或判定标准只动 yml，下次运行生效。
_PROMPT = get("enrich")

SYSTEM_PROMPT = _PROMPT.system_prompt
ENRICH_OUTPUT_SCHEMA = _PROMPT.output_schema


def _build_user_prompt(item: dict, original: dict, *, pre_fetched_text: str | None = None) -> str:
    base = (
        f"文章标题：{item.get('title', '')}\n"
        f"原文链接：{item.get('url', '')}\n"
        f"初步摘要：{item.get('description', '')[:500]}\n"
        f"初步核心事件：{original.get('core_event', '')}\n\n"
    )
    if pre_fetched_text:
        truncated = pre_fetched_text[:15000]
        return (
            base
            + "【已预抓取全文】以下为已获取的原文完整内容，请直接基于此进行分析，无需再调用任何工具：\n\n"
            + f"{truncated}\n\n"
            "步骤：\n"
            "1. 直接阅读上方提供的全文内容。\n"
            "2. 输出 JSON 格式的分析结果。\n"
            "3. content_source 填「full_text」。"
        )
    return (
        base
        + "步骤：\n"
        "1. 首先调用 read_webpage 工具读取原文全文（传入上方原文链接）。\n"
        "2. 仔细阅读完整内容后，再输出 JSON 格式的分析结果。\n"
        "3. content_source 字段必须如实填写：使用了全文填「full_text」，仅摘要则填「summary_only」。\n"
        "【强制】如果 read_webpage 返回「网页读取失败」，必须重试一次；重试仍失败则必须填写「summary_only」。"
    )


# _make_stderr_logger 已抽取到 agent_sdk_runner.make_stderr_logger


def _has_enrich_content(payload: dict[str, Any] | None) -> bool:
    return bool(payload and (payload.get("core_event") or payload.get("hidden_signal") or payload.get("reason")))


async def _enrich_one(item: dict, original: dict, log_event: Any | None = None, *, pre_fetched_text: str | None = None) -> tuple[dict | None, str]:
    """
    使用 output_format 让 CLI 处理 JSON Schema 验证和重试。
    TimeoutError 时按配置进行退避重试；其他异常直接返回。

    Args:
        pre_fetched_text: 已预抓取的全文内容。提供时 MCP tool 直接返回该文本（零网络开销）；
                          未提供时 fallback 到 Jina Reader / Playwright。
    """
    import asyncio
    import anyio

    try:
        from claude_agent_sdk import create_sdk_mcp_server, tool  # type: ignore
    except ImportError:
        return None, "claude_agent_sdk_import_error"

    expected_url = str(item.get("url", "")).strip()
    if not expected_url:
        return None, "missing_url"

    _cached_text = pre_fetched_text  # capture for closure

    @tool(
        "read_webpage",
        "读取文章原文完整内容（优先 Jina Reader；Jina 被拦截时自动降级到 Playwright 浏览器渲染）",
        {"url": str},
    )
    async def read_webpage(args: dict) -> dict:
        if _cached_text:
            return {"content": [{"type": "text", "text": _cached_text}]}
        _jina = get_jina_config()

        def _fetch() -> tuple[bool, str]:
            return read_webpage_text(
                expected_url,
                jina_reader_base=_jina["base_url"],
                jina_max_chars=_jina["max_chars"],
                wechat_timeout_seconds=_jina["wechat_timeout"],
            )[:2]

        ok, payload = await anyio.to_thread.run_sync(_fetch)
        return {"content": [{"type": "text", "text": payload if ok else f"[网页读取失败，请基于已有标题和摘要完成分析] {payload}"}]}

    server = create_sdk_mcp_server(
        name="enrich-tools",
        version="1.0.0",
        tools=[read_webpage],
    )

    allowed_tools = ["mcp__enrich-tools__read_webpage"]
    if ENRICH_ENABLE_SKILLS:
        allowed_tools.append("Skill")

    eid_short = item.get("eid", "")[:8]
    stderr_lines, stderr_logger = make_stderr_logger(f"enrich_agent:{eid_short}", limit=40)

    sdk_logger = make_sdk_logger("enrich", log_event=log_event, eid=item.get("eid", ""), url=expected_url, prompt_version=_PROMPT.version)

    max_attempts = 1 + ENRICH_MAX_RETRIES
    base_timeout = float(ENRICH_ITEM_TIMEOUT_SECONDS)

    for attempt in range(max_attempts):
        # 重试用递减超时：首次已接近完成，重试应更快
        timeout = max(30, int(base_timeout * (0.8 ** attempt)))
        try:
            structured_output = await run_json_agent(
                prompt=_build_user_prompt(item, original, pre_fetched_text=pre_fetched_text),
                system_prompt=SYSTEM_PROMPT,
                schema=ENRICH_OUTPUT_SCHEMA,
                allowed_tools=allowed_tools,
                mcp_servers={"enrich-tools": server},
                max_turns=param("enrich", "max_turns", 20),
                max_budget_usd=ENRICH_MAX_BUDGET_USD,
                timeout_seconds=timeout,
                cwd=Path.cwd(),
                setting_sources=["project"] if ENRICH_ENABLE_SKILLS else None,
                stderr=stderr_logger,
                sdk_log=sdk_logger,
            )
            if attempt > 0 and log_event:
                log_event("INFO", "enrich_retry_ok", stage="enrich", eid=item.get("eid", ""), attempt=attempt + 1)
            return structured_output, "ok"
        except TimeoutError:
            if attempt < max_attempts - 1:
                if log_event:
                    log_event(
                        "WARN",
                        "enrich_retry",
                        stage="enrich",
                        eid=item.get("eid", ""),
                        attempt=attempt + 1,
                        max_attempts=max_attempts,
                        wait=ENRICH_RETRY_BACKOFF_SECONDS,
                        next_timeout=timeout,
                    )
                await asyncio.sleep(ENRICH_RETRY_BACKOFF_SECONDS)
                continue
            # 所有重试耗尽
            if stderr_lines:
                print(f"[enrich_agent] eid={eid_short} error: timeout after {max_attempts} attempts", flush=True)
            return None, f"timeout_after_{max_attempts}_attempts"
        except Exception as e:
            # 非 TimeoutError 不重试
            if stderr_lines:
                print(f"[enrich_agent] eid={eid_short} error: {' | '.join(stderr_lines[-5:])}", flush=True)
            return None, str(e)

    return None, "no_result"


async def _enrich_all(
    items_to_enrich: list[tuple[dict, dict]],
    analyses: dict[str, dict],
    log_event: Any,
    *,
    pre_fetched_texts: dict[str, str] | None = None,
    on_item_done: Any | None = None,
) -> dict[str, int]:
    import anyio

    # 下面多处直接调 log_event(...)，在入口归一化成 no-op，
    # 免得每个调用点都要写 if log_event 保护。
    if log_event is None:
        def log_event(*_args: Any, **_kwargs: Any) -> None:
            return None

    semaphore = anyio.Semaphore(ENRICH_MAX_WORKERS)
    stats = {"started": 0, "succeeded": 0, "failed": 0, "empty": 0, "retried": 0, "retried_succeeded": 0}

    async def run_one(item: dict, original: dict) -> None:
        eid = item["eid"]
        async with semaphore:
            started_at = time.perf_counter()
            stats["started"] += 1
            log_event(
                "INFO",
                "enrich_item_start",
                stage="enrich",
                eid=eid,
                url=str(item.get("url", "")).strip(),
            )
            try:
                enriched, reason = await _enrich_one(
                    item, original, log_event,
                    pre_fetched_text=(pre_fetched_texts or {}).get(eid),
                )
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                if enriched:
                    is_retry_ok = reason.startswith("timeout_after")
                    if is_retry_ok:
                        stats["retried_succeeded"] += 1
                    merged = {**original}
                    for key in ("core_event", "reason", "hidden_signal", "actionable"):
                        val = str(enriched.get(key, "")).strip()
                        if val:
                            merged[key] = val
                    tags = enriched.get("tags", [])
                    if isinstance(tags, list):
                        merged["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()]
                    importance = enriched.get("importance_score")
                    if isinstance(importance, int) and 1 <= importance <= 5:
                        merged["importance_score"] = importance
                    content_source = str(enriched.get("content_source", "")).strip()
                    if content_source in {"full_text", "summary_only"}:
                        merged["content_source"] = content_source
                    for key, upper in (
                        ("signal_type", 12),
                        ("evidence_type", 12),
                        ("evidence_strength", 5),
                        ("novelty_score", 5),
                        ("impact_horizon", 5),
                        ("market_stage", 6),
                        ("confidence", 5),
                    ):
                        value = enriched.get(key)
                        if isinstance(value, int) and 1 <= value <= upper:
                            merged[key] = value
                    audience = enriched.get("audience", [])
                    if isinstance(audience, list):
                        merged["audience"] = [
                            value for value in audience
                            if isinstance(value, int) and 1 <= value <= 8
                        ][:3]
                    for key in ("entities", "watch_keywords"):
                        values = enriched.get(key, [])
                        if isinstance(values, list):
                            merged[key] = [str(value).strip() for value in values if str(value).strip()][:8]
                    for key in ("cluster_hint", "prediction", "disconfirming_evidence"):
                        value = str(enriched.get(key, "")).strip()
                        if value:
                            merged[key] = value
                    merged["enriched"] = True
                    analyses[eid] = merged
                    stats["succeeded"] += 1
                    log_event(
                        "INFO",
                        "enrich_done",
                        stage="enrich",
                        eid=eid,
                        duration_ms=duration_ms,
                        content_source=merged.get("content_source", ""),
                        importance_score=merged.get("importance_score"),
                        signal_type=merged.get("signal_type"),
                        evidence_type=merged.get("evidence_type"),
                        evidence_strength=merged.get("evidence_strength"),
                        novelty_score=merged.get("novelty_score"),
                        impact_horizon=merged.get("impact_horizon"),
                        market_stage=merged.get("market_stage"),
                        confidence=merged.get("confidence"),
                        cluster_hint=merged.get("cluster_hint", ""),
                        hidden_signal=merged.get("hidden_signal", "")[:40],
                    )
                    # 增量落库钩子。回调做的是阻塞 DB IO，放到线程里跑，
                    # 否则会堵住事件循环、拖慢其他并发中的 enrich。
                    # 回调异常不能影响 enrich 本身（落库失败不该让分析结果丢失）。
                    if on_item_done is not None:
                        try:
                            await anyio.to_thread.run_sync(on_item_done, item, merged)
                        except Exception as cb_exc:  # noqa: BLE001
                            stats["flush_failed"] = stats.get("flush_failed", 0) + 1
                            log_event(
                                "WARN",
                                "enrich_flush_failed",
                                stage="enrich",
                                eid=eid,
                                error=f"{type(cb_exc).__name__}: {str(cb_exc)[:160]}",
                            )
                else:
                    is_timeout = "timeout_after" in reason
                    if is_timeout:
                        stats["retried"] += 1
                    stats["empty"] += 1
                    log_event("WARN", "enrich_failed", stage="enrich", eid=eid, duration_ms=duration_ms, error=f"no_result:{reason}")
            except Exception as e:
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                stats["failed"] += 1
                log_event("WARN", "enrich_failed", stage="enrich", eid=eid, duration_ms=duration_ms, error=str(e))

    async with anyio.create_task_group() as tg:
        for item, original in items_to_enrich:
            tg.start_soon(run_one, item, original)
    return stats
def analyze_candidates_with_agent(
    *,
    candidates: list[dict],
    log_event: Any,
    pre_fetched_texts: dict[str, str] | None = None,
    on_item_done: Any | None = None,
) -> dict[str, dict[str, Any]]:
    analyses: dict[str, dict[str, Any]] = {}
    if not candidates:
        return analyses

    seed: dict[str, dict[str, Any]] = {
        str(item.get("eid", "")): {
            "reason": "",
            "hidden_signal": "",
            "actionable": "",
            "tags": [],
            "core_event": "",
        }
        for item in candidates
        if str(item.get("eid", "")).strip()
    }
    analyses.update(seed)
    _enrich_candidates = [(item, analyses[item["eid"]]) for item in candidates if item.get("eid") in analyses]

    if not ENRICH_AGENT_ENABLED:
        log_event("INFO", "enrich_skipped", stage="enrich", reason="ENRICH_AGENT_ENABLED=false")
        return analyses

    if not _enrich_candidates:
        log_event("INFO", "enrich_skipped", stage="enrich", reason="no_candidates")
        return analyses

    log_event("INFO", "enrich_start", stage="enrich", count=len(_enrich_candidates), max_workers=ENRICH_MAX_WORKERS)

    try:
        import anyio
        from functools import partial
        enrich_stats = anyio.run(partial(_enrich_all, _enrich_candidates, analyses, log_event, pre_fetched_texts=pre_fetched_texts, on_item_done=on_item_done))
        log_event(
            "INFO",
            "enrich_complete",
            stage="enrich",
            enriched=enrich_stats.get("succeeded", 0),
            failed=enrich_stats.get("failed", 0),
            empty=enrich_stats.get("empty", 0),
            started=enrich_stats.get("started", len(_enrich_candidates)),
            retried=enrich_stats.get("retried", 0),
            retried_succeeded=enrich_stats.get("retried_succeeded", 0),
        )
    except Exception as e:
        log_event("WARN", "agent_analysis_error", stage="agent", error=str(e))
    return analyses
