"""
全局情报深度分析 Agent
使用 Claude Agent SDK 驱动 claude CLI 进程，对候选情报进行二次深度分析。
Agent 通过内置 Read 工具读取今日候选情报和历史 signals 文件，通过 Jina Reader API (r.jina.ai) 抓取原文，
最终以结构化 JSON 格式输出分析报告。

设计原则：
- 使用 output_format 让 CLI 自动验证 JSON Schema（内置 5 次重试）
- 直接信任 structured_output，失败即跳过
- 可通过 GLOBAL_AGENT_ENABLED=false 关闭
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import re

from rss2cubox.agent_sdk_runner import _StructuredOutputError, run_json_agent
from rss2cubox.webpage_reader import read_webpage_text

GLOBAL_AGENT_ENABLED = os.getenv("GLOBAL_AGENT_ENABLED", "true").lower() not in ("false", "0", "no")
GLOBAL_AGENT_ENABLE_SKILLS = os.getenv("GLOBAL_AGENT_ENABLE_SKILLS", "true").lower() in ("1", "true", "yes")
GLOBAL_AGENT_MIN_CANDIDATES = max(1, int(os.getenv("GLOBAL_AGENT_MIN_CANDIDATES", "3")))
_global_agent_max_budget_raw = os.getenv("GLOBAL_AGENT_MAX_BUDGET_USD", "50.0").strip()
try:
    GLOBAL_AGENT_MAX_BUDGET_USD = float(_global_agent_max_budget_raw) if _global_agent_max_budget_raw else None
except ValueError:
    GLOBAL_AGENT_MAX_BUDGET_USD = None

_SIGNAL_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "maxLength": 200},
        "source_urls": {
            "type": "array",
            "items": {"type": "string", "format": "uri"},
            "maxItems": 10,
        },
        "source_titles": {
            "type": "array",
            "items": {"type": "string", "maxLength": 200},
            "maxItems": 10,
        },
    },
    "required": ["text"],
}

# JSON Schema 用于 output_format（CLI 层自动验证）
GLOBAL_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "trends": {
            "type": "array",
            "items": _SIGNAL_ITEM_SCHEMA,
        },
        "weak_signals": {
            "type": "array",
            "items": _SIGNAL_ITEM_SCHEMA,
        },
        "daily_advices": {
            "type": "array",
            "items": _SIGNAL_ITEM_SCHEMA,
        },
        "key_topics": {
            "type": "array",
            "items": {"type": "string"},
        },
        "confidence_level": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
    },
    "required": ["trends", "weak_signals", "daily_advices"],
}

SYSTEM_PROMPT = (
    "你是一位顶级科技产业与投资分析师，尤其深耕 AI 与智能体（AI Agent）领域，专注从海量 RSS 信息流中提炼宏观趋势与深层弱信号。"
    "你拥有 read_webpage 工具，可随时获取任何 URL 的完整正文（优先走 Jina Reader 返回 Markdown；"
    "若目标站点屏蔽了 Jina（如掘金返回 451），工具会自动降级到 Playwright 真实浏览器渲染并提取正文）。"
    "对于值得深挖的情报，主动调用 read_webpage 阅读原文，不要仅凭摘要做判断。"
    "【关注重点】在提炼趋势和弱信号时，请特别关注以下方向：\n"
    "- AI 模型能力突破（新架构、新基准、Scaling Law 变化）\n"
    "- AI Agent / 智能体框架、工具链、多智能体协作、Agent 运行时\n"
    "- LLM 应用层创新（RAG、推理优化、长上下文、多模态）\n"
    "- 开源模型与生态动态（权重开源、微调方案、社区趋势）\n"
    "- AI 基础设施（算力、芯片、推理优化、训练框架）\n"
    "以上方向的信号应在 trends 和 weak_signals 中获得适当体现，但不要刻意拔高——仍需基于事实客观判断。\n"
    "【溯源要求】输出每条 trend / weak_signal / daily_advice 时，必须同时标注支撑来源：\n"
    "- source_urls: 支撑该结论的原文 URL 列表（从输入情报中选取最相关的 1-5 条）\n"
    "- source_titles: 对应的文章标题（与 source_urls 一一对应）\n"
    "- 如果某条结论是综合推断、无法归因到具体文章，source_urls 可为空数组 []\n"
    "- 绝对不要编造 URL，只使用输入数据中已存在的 url 字段\n"
    "完成所有分析后，直接输出结构化 JSON 格式的报告。"
    "所有输出文字必须使用简体中文，语言专业、精炼，不要废话。"
)

JINA_READER_BASE = "https://r.jina.ai/"
JINA_MAX_CHARS = 30000
WECHAT_FETCH_TIMEOUT_SECONDS = max(10, int(os.getenv("WECHAT_FETCH_TIMEOUT_SECONDS", "30")))


def _build_user_prompt(signals_file: str, history_file: str, total: int) -> str:
    deep_read_target = min(max(total, 1), 8)
    return f"""今日候选情报共 {total} 条，已保存到文件：{signals_file}
所有历史 signals 已保存到文件：{history_file}

请完成以下任务：
1. 首先使用 Read 工具读取今日候选情报 {signals_file}
2. 再使用 Read 工具读取历史 signals {history_file}
3. 从中挑选最值得深挖的 {deep_read_target} 条左右条目，使用 read_webpage 工具阅读原文完整内容。
4. 综合所有信息后，直接输出结构化 JSON 格式的报告：
   - trends: 宏观技术/行业趋势归纳，3-5 条，每条为 {{text, source_urls, source_titles}} 对象
   - weak_signals: 潜藏的弱信号或暗流，2-4 条，每条为 {{text, source_urls, source_titles}} 对象
   - daily_advices: 给工程师/独立开发者的今日行动建议，2-4 条，每条为 {{text, source_urls, source_titles}} 对象
   - key_topics: 本次分析的核心主题标签，2-4 个关键词/短语（如 "AI Agent 竞争"、"多模态推理"、"开源模型定价"）
   - confidence_level: 整体分析置信度，只输出 "high" / "medium" / "low" 三者之一
   每条趋势/弱信号/建议必须附带 source_urls 和 source_titles，引用自你读取过的候选情报中的真实 URL

所有内容必须使用简体中文。"""


def _make_stderr_logger(prefix: str, limit: int = 80) -> tuple[list[str], Any]:
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


def _normalize_text_list(value: Any, key_hint: str) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = ""
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            preferred = item.get(key_hint)
            if isinstance(preferred, str):
                text = preferred.strip()
            else:
                for v in item.values():
                    if isinstance(v, str) and v.strip():
                        text = v.strip()
                        break
        else:
            text = str(item).strip()
        if text:
            out.append(text)
    return out


def _normalize_signal_item(item: Any) -> dict[str, Any] | None:
    """归一化单条信号：兼容 string（旧格式）和 dict（新格式带溯源）。"""
    if isinstance(item, str):
        text = item.strip()
        return {"text": text, "source_urls": [], "source_titles": []} if text else None

    if not isinstance(item, dict):
        return None

    text = str(item.get("text", "")).strip()
    if not text:
        return None

    urls = item.get("source_urls", [])
    titles = item.get("source_titles", [])

    if isinstance(urls, list):
        urls = [str(u).strip() for u in urls if isinstance(u, str) and u.strip()]
    else:
        urls = []

    if isinstance(titles, list):
        titles = [str(t).strip() for t in titles if isinstance(t, str) and t.strip()]
    else:
        titles = []

    max_len = min(len(urls), len(titles), 10)
    return {
        "text": text[:200],
        "source_urls": urls[:max_len],
        "source_titles": titles[:max_len],
    }


def _extract_json_from_text(text: str) -> dict[str, Any] | None:
    """从可能包含前缀文字或 markdown 代码块的文本中提取 JSON 对象。"""
    if not text or not isinstance(text, str):
        return None
    # 策略1：查找 ```json ... ``` 代码块
    code_block_match = re.search(r"```(?:json)?\s*\n(.*?)\n\s*```", text, re.DOTALL)
    if code_block_match:
        candidate = code_block_match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    # 策略2：查找最外层 { ... }
    brace_start = text.find("{")
    if brace_start >= 0:
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[brace_start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
    return None


def _normalize_global_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "trends": [_normalize_signal_item(x) for x in payload.get("trends", []) if _normalize_signal_item(x)],
        "weak_signals": [_normalize_signal_item(x) for x in payload.get("weak_signals", []) if _normalize_signal_item(x)],
        "daily_advices": [_normalize_signal_item(x) for x in payload.get("daily_advices", []) if _normalize_signal_item(x)],
        "key_topics": _normalize_text_list(payload.get("key_topics", []), "topic"),
        "confidence_level": payload.get("confidence_level", "medium")
        if payload.get("confidence_level") in ("high", "medium", "low")
        else "medium",
    }


async def _run_agent(
    high_value_items: list[dict],
    history_signals: dict[str, list[str]],
    log_event: Any | None = None,
) -> dict[str, Any] | None:
    """
    使用 output_format 让 CLI 处理 JSON Schema 验证和重试。
    直接信任 structured_output，失败即返回错误。
    """
    import anyio

    try:
        from claude_agent_sdk import create_sdk_mcp_server, tool  # type: ignore
    except ImportError:
        print("[global_agent] claude-agent-sdk 未安装，跳过全局分析", flush=True)
        return None

    # 将今日信号数据写入临时文件
    signals_data = [
        {
            "url": r["url"],
            "title": r.get("title", ""),
            "hidden_signal": r.get("hidden_signal", ""),
            "core_event": r.get("core_event", ""),
            "reason": r.get("reason", ""),
            "importance_score": r.get("importance_score"),
            "novelty_score": r.get("novelty_score"),
            "signal_type": r.get("signal_type"),
            "confidence": r.get("confidence"),
            "evidence_strength": r.get("evidence_strength"),
            "tags": r.get("tags", []),
            "entities": r.get("entities", []),
            "cluster_hint": r.get("cluster_hint", ""),
            "actionable": r.get("actionable", ""),
            "market_stage": r.get("market_stage"),
        }
        for r in high_value_items
    ]
    signals_tmp_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    signals_file_path: str | None = None
    try:
        json.dump(signals_data, signals_tmp_file, ensure_ascii=False, indent=2)
        signals_tmp_file.flush()
        signals_file_path = signals_tmp_file.name
    finally:
        signals_tmp_file.close()

    # 将历史 signals 写入临时文件
    history_tmp_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    history_file_path: str | None = None
    try:
        json.dump(history_signals, history_tmp_file, ensure_ascii=False, indent=2)
        history_tmp_file.flush()
        history_file_path = history_tmp_file.name
    finally:
        history_tmp_file.close()

    @tool(
        "read_webpage",
        "读取指定 URL 的正文（优先 Jina Reader 返回 Markdown；Jina 被拦截时自动降级到 Playwright 浏览器渲染）",
        {"url": str},
    )
    async def read_webpage(args: dict) -> dict:
        url = args["url"]

        def _fetch() -> tuple[bool, str]:
            ok, content, _source = read_webpage_text(
                url,
                jina_reader_base=JINA_READER_BASE,
                jina_max_chars=JINA_MAX_CHARS,
                wechat_timeout_seconds=WECHAT_FETCH_TIMEOUT_SECONDS,
            )
            return ok, content

        ok, content = await anyio.to_thread.run_sync(_fetch)
        if not ok:
            content = f"[网页读取失败] {content}"
        return {"content": [{"type": "text", "text": content}]}

    server = create_sdk_mcp_server(
        name="insights-tools",
        version="1.0.0",
        tools=[read_webpage],
    )

    allowed_tools = [
        "mcp__insights-tools__read_webpage",
        "Read",
        "Grep",
        "Glob",
    ]
    if GLOBAL_AGENT_ENABLE_SKILLS:
        allowed_tools.append("Skill")

    stderr_lines, stderr_logger = _make_stderr_logger("global_agent")

    def sdk_logger(event: str, **fields: Any) -> None:
        if log_event is None:
            return
        level = "WARN" if event.endswith("_error") or event == "agent_sdk_no_result" else "INFO"
        log_event(
            level,
            event,
            stage="agent_sdk",
            agent="global",
            source_count=len(high_value_items),
            **fields,
        )

    try:
        structured_output = await run_json_agent(
            prompt=_build_user_prompt(signals_file_path, history_file_path, len(high_value_items)),
            system_prompt=SYSTEM_PROMPT,
            schema=GLOBAL_OUTPUT_SCHEMA,
            allowed_tools=allowed_tools,
            mcp_servers={"insights-tools": server},
            max_turns=100,
            max_budget_usd=GLOBAL_AGENT_MAX_BUDGET_USD,
            cwd=Path.cwd(),
            setting_sources=["project"] if GLOBAL_AGENT_ENABLE_SKILLS else None,
            stderr=stderr_logger,
            sdk_log=sdk_logger,
        )
        result = _normalize_global_payload(structured_output)
        print("[global_agent] structured_output: ok", flush=True)
        return result
    except _StructuredOutputError as e:
        # Schema 验证失败，尝试从原始文本中 fallback 提取 JSON
        print("[global_agent] structured_output 为空，尝试 fallback 解析...", flush=True)
        fallback = _extract_json_from_text(e.raw_text)
        if fallback and isinstance(fallback, dict):
            result = _normalize_global_payload(fallback)
            total = sum(len(result.get(k, [])) for k in ("trends", "weak_signals", "daily_advices"))
            print(f"[global_agent] fallback 解析成功，共 {total} 条信号", flush=True)
            return result
        print(f"[global_agent] fallback 解析也失败，原始文本前 500 字符: {e.raw_text[:500]}", flush=True)
    except Exception as e:
        if stderr_lines:
            print(f"[global_agent] error: {' | '.join(stderr_lines[-8:])}", flush=True)
        else:
            print(f"[global_agent] error: {e}", flush=True)
    finally:
        # 清理临时文件
        if signals_file_path:
            try:
                Path(signals_file_path).unlink(missing_ok=True)
            except Exception:
                pass
        if history_file_path:
            try:
                Path(history_file_path).unlink(missing_ok=True)
            except Exception:
                pass

    return None


def run_global_analysis(
    analyses: dict[str, dict],
    candidates: list[dict],
    log_event: Any | None = None,
) -> None:
    """
    从本次 pipeline 的分析结果中筛出可用于全局分析的条目，
    驱动 Claude Agent 进行二次深度分析并写入 Neon DB。
    """
    import anyio

    if not GLOBAL_AGENT_ENABLED:
        print("[global_agent] GLOBAL_AGENT_ENABLED=false，跳过全局分析", flush=True)
        return

    # 拼装本轮可用于全局分析的条目
    high_value: list[dict] = []
    for c in candidates:
        eid = c.get("eid", "")
        analysis = analyses.get(eid, {})
        hidden_signal = str(analysis.get("hidden_signal", "")).strip()
        core_event = str(analysis.get("core_event", "")).strip()
        reason = str(analysis.get("reason", "")).strip()
        if not (hidden_signal or core_event or reason):
            continue
        high_value.append({
            "url": c.get("url", ""),
            "title": c.get("title", ""),
            "hidden_signal": hidden_signal,
            "core_event": core_event,
            "reason": reason,
            "importance_score": analysis.get("importance_score"),
            "novelty_score": analysis.get("novelty_score"),
            "signal_type": analysis.get("signal_type"),
            "confidence": analysis.get("confidence"),
            "evidence_strength": analysis.get("evidence_strength"),
            "tags": analysis.get("tags", []),
            "entities": analysis.get("entities", []),
            "cluster_hint": analysis.get("cluster_hint", ""),
            "actionable": analysis.get("actionable", ""),
            "market_stage": analysis.get("market_stage"),
        })

    if not high_value:
        print("[global_agent] 无可用情报，跳过全局分析", flush=True)
        return

    # 保持主流程顺序，取前 200 条
    high_value = high_value[:200]

    # 候选数量不足最低阈值时跳过（避免低源数量导致高空白率）
    if len(high_value) < GLOBAL_AGENT_MIN_CANDIDATES:
        print(
            f"[global_agent] 候选情报 {len(high_value)} 条不足最低阈值 {GLOBAL_AGENT_MIN_CANDIDATES}，跳过全局分析",
            flush=True,
        )
        return

    # 从数据库读取所有历史 signals
    history_signals = {"trends": [], "weak_signals": [], "daily_advices": []}
    try:
        from rss2cubox.db_client import get_all_global_insights
        all_insights = get_all_global_insights()
        for insight in all_insights:
            history_signals["trends"].extend(insight.get("trends", []))
            history_signals["weak_signals"].extend(insight.get("weak_signals", []))
            history_signals["daily_advices"].extend(insight.get("daily_advices", []))
        print(f"[global_agent] 已加载 {len(all_insights)} 条历史 insights", flush=True)
    except Exception as e:
        print(f"[global_agent] 加载历史 signals 失败: {e}", flush=True)

    print(f"[global_agent] 启动全局 Agent 分析，共 {len(high_value)} 条候选情报...", flush=True)

    if log_event is None:
        result = anyio.run(_run_agent, high_value, history_signals)
    else:
        result = anyio.run(_run_agent, high_value, history_signals, log_event)

    if not result:
        print("[global_agent] Agent 未返回有效报告", flush=True)
        return

    total_items = len(result.get("trends", [])) + len(result.get("weak_signals", [])) + len(result.get("daily_advices", []))
    if total_items == 0:
        print(f"[global_agent] Agent 返回空结果（trends/weak_signals/daily_advices 均为空），跳过写入，source_count={len(high_value)}", flush=True)
        return

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_count": len(high_value),
        "trends": result.get("trends", []),
        "weak_signals": result.get("weak_signals", []),
        "daily_advices": result.get("daily_advices", []),
        "key_topics": result.get("key_topics", []),
        "confidence_level": result.get("confidence_level", "medium"),
    }
    neon_url = os.getenv("NEON_DATABASE_URL", "").strip()
    if neon_url:
        try:
            from rss2cubox.db import save_global_insights
            save_global_insights(neon_url, payload)
            print("[global_agent] 全局分析完成，insights 已写入 Neon DB", flush=True)
        except Exception as e:
            print(f"[global_agent] Neon DB 写入失败: {e}", flush=True)
    else:
        print("[global_agent] 全局分析完成，但未配置 NEON_DATABASE_URL，结果未保存", flush=True)

    # 同时写入本地 PostgreSQL（可选，失败不影响主流程）
    try:
        from rss2cubox.db_client import save_global_insights as save_local_insights
        save_local_insights(payload)
    except Exception as e:
        print(f"[global_agent] 本地 DB 写入失败（可忽略）: {e}", flush=True)
