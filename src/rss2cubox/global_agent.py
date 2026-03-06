"""
全局情报深度分析 Agent
使用 Claude Agent SDK 驱动 claude CLI 进程，对高价值情报进行二次深度分析。
Agent 通过 read_signals_file 工具读取信号文件，通过 Jina Reader API (r.jina.ai) 抓取原文，
最终以结构化 JSON 格式输出分析报告。

设计原则：
- 使用 output_format 让 CLI 自动验证 JSON Schema（CLI 内置重试）
- 应用层仅对 timeout/网络错误重试
- 单条失败静默跳过
- 可通过 GLOBAL_AGENT_ENABLED=false 关闭
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests as _requests

GLOBAL_AGENT_ENABLED = os.getenv("GLOBAL_AGENT_ENABLED", "true").lower() not in ("false", "0", "no")
GLOBAL_AGENT_ENABLE_SKILLS = os.getenv("GLOBAL_AGENT_ENABLE_SKILLS", "true").lower() in ("1", "true", "yes")
GLOBAL_AGENT_TIMEOUT_SECONDS = max(60, int(os.getenv("GLOBAL_AGENT_TIMEOUT_SECONDS", "300")))
GLOBAL_AGENT_APP_MAX_RETRIES = int(os.getenv("GLOBAL_AGENT_APP_MAX_RETRIES", "2"))
GLOBAL_AGENT_RETRY_DELAY_BASE = float(os.getenv("GLOBAL_AGENT_RETRY_DELAY_BASE", "2.0"))

# JSON Schema 用于 output_format（CLI 层自动验证）
GLOBAL_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "trends": {
            "type": "array",
            "items": {"type": "string"},
        },
        "weak_signals": {
            "type": "array",
            "items": {"type": "string"},
        },
        "daily_advices": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["trends", "weak_signals", "daily_advices"],
}

SYSTEM_PROMPT = (
    "你是一位顶级科技产业与投资分析师，专注从海量 RSS 信息流中提炼宏观趋势与深层弱信号。"
    "你拥有 read_webpage 工具，可随时获取任何 URL 的完整干净正文（由 Jina Reader 处理，格式为 Markdown）。"
    "对于值得深挖的情报，主动调用 read_webpage 阅读原文，不要仅凭摘要做判断。"
    "完成所有分析后，直接输出结构化 JSON 格式的报告。"
    "所有输出文字必须使用简体中文，语言专业、精炼，不要废话。"
)

JINA_READER_BASE = "https://r.jina.ai/"
JINA_MAX_CHARS = 8000


def _build_user_prompt(signals_file: str, total: int) -> str:
    return f"""今日高价值情报（score ≥ 0.85）共 {total} 条，已保存到文件：{signals_file}

请完成以下任务：
1. 首先调用 read_signals_file 工具读取完整信号列表。
2. 从中挑选 10-20 条你认为最值得深挖的条目，使用 read_webpage 工具阅读原文完整内容。
3. 综合所有信息后，直接输出结构化 JSON 格式的报告：
   - trends: 宏观技术/行业趋势归纳，3-5 条，每条 ≤ 80 字
   - weak_signals: 潜藏的弱信号或暗流，2-4 条，每条 ≤ 80 字
   - daily_advices: 给工程师/独立开发者的今日行动建议，2-4 条，每条 ≤ 60 字

所有内容必须使用简体中文。"""


async def _run_agent(high_value_items: list[dict]) -> dict[str, Any] | None:
    """
    使用 output_format 让 CLI 处理 JSON Schema 验证和重试。
    应用层仅对 timeout/网络错误进行有限重试。
    """
    import json

    import anyio

    try:
        from claude_agent_sdk import (  # type: ignore
            ClaudeAgentOptions,
            ResultMessage,
            create_sdk_mcp_server,
            query,
            tool,
        )
    except ImportError:
        print("[global_agent] claude-agent-sdk 未安装，跳过全局分析", flush=True)
        return None

    # 将信号数据写入临时文件
    signals_data = [
        {
            "url": r["url"],
            "title": r.get("hidden_signal") or r.get("title", ""),
            "core_event": r.get("core_event", ""),
            "score": round(r.get("score", 0), 2),
        }
        for r in high_value_items
    ]
    tmp_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    try:
        json.dump(signals_data, tmp_file, ensure_ascii=False, indent=2)
        tmp_file.flush()
        signals_file_path = tmp_file.name
    finally:
        tmp_file.close()

    @tool(
        "read_signals_file",
        "读取今日高价值情报信号文件，返回完整的 JSON 列表",
        {},
    )
    async def read_signals_file(args: dict) -> dict:
        try:
            content = Path(signals_file_path).read_text(encoding="utf-8")
        except Exception as e:
            content = f"[读取失败: {e}]"
        return {"content": [{"type": "text", "text": content}]}

    @tool(
        "read_webpage",
        "通过 Jina Reader 获取指定 URL 的干净正文 Markdown，用于深度阅读原文",
        {"url": str},
    )
    async def read_webpage(args: dict) -> dict:
        url = args["url"]
        jina_url = f"{JINA_READER_BASE}{url}"

        def _fetch() -> tuple[bool, str]:
            try:
                resp = _requests.get(
                    jina_url,
                    headers={"Accept": "text/plain", "x-respond-with": "markdown"},
                    timeout=20,
                )
                resp.raise_for_status()
                return True, resp.text[:JINA_MAX_CHARS]
            except Exception as e:
                return False, f"[读取失败: {e}]"

        ok, content = await anyio.to_thread.run_sync(_fetch)
        if not ok:
            content = f"[网页读取失败] {content}"
        return {"content": [{"type": "text", "text": content}]}

    server = create_sdk_mcp_server(
        name="insights-tools",
        version="1.0.0",
        tools=[read_signals_file, read_webpage],
    )

    allowed_tools = [
        "mcp__insights-tools__read_signals_file",
        "mcp__insights-tools__read_webpage",
    ]
    if GLOBAL_AGENT_ENABLE_SKILLS:
        allowed_tools.append("Skill")

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        allowed_tools=allowed_tools,
        mcp_servers={"insights-tools": server},
        permission_mode="acceptEdits",
        max_turns=100,
        cwd=Path.cwd(),
        setting_sources=["project"] if GLOBAL_AGENT_ENABLE_SKILLS else None,
        # 使用 output_format 让 CLI 自动验证 JSON Schema（CLI 内置重试）
        output_format={"type": "json_schema", "schema": GLOBAL_OUTPUT_SCHEMA},
    )

    last_error = "no_result"

    # 应用层重试：仅针对 timeout 和网络错误
    for attempt in range(GLOBAL_AGENT_APP_MAX_RETRIES + 1):
        try:
            with anyio.fail_after(GLOBAL_AGENT_TIMEOUT_SECONDS):
                async for message in query(prompt=_build_user_prompt(signals_file_path, len(high_value_items)), options=options):
                    if isinstance(message, ResultMessage):
                        # CLI 层 JSON Schema 验证成功
                        if message.structured_output:
                            result = message.structured_output
                            if result.get("trends") or result.get("weak_signals") or result.get("daily_advices"):
                                print("[global_agent] validated: ok", flush=True)
                                # 清理临时文件
                                try:
                                    Path(signals_file_path).unlink(missing_ok=True)
                                except Exception:
                                    pass
                                return result
                            else:
                                last_error = "empty_fields"
                        # CLI 层重试耗尽
                        elif message.subtype == "error_max_structured_output_retries":
                            last_error = "cli_retry_exhausted"
                        # 其他错误
                        elif message.is_error:
                            last_error = f"subtype:{message.subtype}"
                        else:
                            last_error = "no_structured_output"
        except TimeoutError:
            last_error = "timeout"
            # timeout 可以重试
        except Exception as e:
            last_error = f"error:{type(e).__name__}"
            # 某些网络错误可以重试

        # 指数退避重试（最后一次不等待）
        if attempt < GLOBAL_AGENT_APP_MAX_RETRIES and last_error in ("timeout", "error:ConnectionError", "error:HTTPError"):
            delay = GLOBAL_AGENT_RETRY_DELAY_BASE * (2 ** attempt)
            print(f"[global_agent] retry {attempt + 1}, wait {delay}s, reason={last_error}", flush=True)
            await anyio.sleep(delay)
        else:
            # 其他错误不重试
            break

    # 清理临时文件
    try:
        Path(signals_file_path).unlink(missing_ok=True)
    except Exception:
        pass

    print(f"[global_agent] failed: {last_error}", flush=True)
    return None


def run_global_analysis(
    analyses: dict[str, dict],
    candidates: list[dict],
) -> None:
    """
    从本次 pipeline 的分析结果中筛出高价值条目，
    驱动 Claude Agent 进行二次深度分析并写入 Neon DB。
    """
    import anyio

    if not GLOBAL_AGENT_ENABLED:
        print("[global_agent] GLOBAL_AGENT_ENABLED=false，跳过全局分析", flush=True)
        return

    # 拼装高价值条目 (score >= 0.85)
    high_value: list[dict] = []
    for c in candidates:
        eid = c.get("eid", "")
        analysis = analyses.get(eid, {})
        score = analysis.get("score", 0)
        if score >= 0.85:
            high_value.append({
                "url": c.get("url", ""),
                "title": c.get("title", ""),
                "hidden_signal": analysis.get("hidden_signal", ""),
                "core_event": analysis.get("core_event", ""),
                "score": score,
            })

    if not high_value:
        print("[global_agent] 无高价值情报，跳过全局分析", flush=True)
        return

    # 按 score 降序，取前 200 条
    high_value.sort(key=lambda x: x["score"], reverse=True)
    high_value = high_value[:200]

    print(f"[global_agent] 启动全局 Agent 分析，共 {len(high_value)} 条高价值情报...", flush=True)

    result = anyio.run(_run_agent, high_value)

    if not result:
        print("[global_agent] Agent 未返回有效报告", flush=True)
        return

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_count": len(high_value),
        "trends": result.get("trends", []),
        "weak_signals": result.get("weak_signals", []),
        "daily_advices": result.get("daily_advices", []),
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
