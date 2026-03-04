"""
全局情报深度分析 Agent
使用 Claude Agent SDK 驱动 claude CLI 进程，对高价值情报进行二次深度分析。
Agent 通过 Jina Reader API (r.jina.ai) 抓取原文 Markdown，最终以结构化 JSON 提交分析报告。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests as _requests
from pydantic import BaseModel, Field, ValidationError, field_validator

GLOBAL_INSIGHTS_FILE = Path(os.getenv("WEB_INSIGHTS_FILE", "web/public/data/global_insights.json"))
GLOBAL_AGENT_ENABLE_SKILLS = os.getenv("GLOBAL_AGENT_ENABLE_SKILLS", "true").lower() in ("1", "true", "yes")

SYSTEM_PROMPT = (
    "你是一位顶级科技产业与投资分析师，专注从海量 RSS 信息流中提炼宏观趋势与深层弱信号。"
    "你拥有 read_webpage 工具，可随时获取任何 URL 的完整干净正文（由 Jina Reader 处理，格式为 Markdown）。"
    "对于值得深挖的情报，主动调用 read_webpage 阅读原文，不要仅凭摘要做判断。"
    "完成所有分析后，你必须调用 submit_insights 工具输出结构化报告。"
    "所有输出文字必须使用简体中文，语言专业、精炼，不要废话。"
)

JINA_READER_BASE = "https://r.jina.ai/"
JINA_MAX_CHARS = 8000  # 截断防止 Token 超限


class GlobalInsightsReport(BaseModel):
    trends: list[str] = Field(default_factory=list)
    weak_signals: list[str] = Field(default_factory=list)
    daily_advices: list[str] = Field(default_factory=list)

    @field_validator("trends", "weak_signals", "daily_advices", mode="before")
    @classmethod
    def _coerce_items(cls, value: Any) -> list[str]:
        return _to_str_list(value)


def _split_text_to_items(text: str) -> list[str]:
    normalized = (
        text.replace("<br/>", "\n")
        .replace("<br />", "\n")
        .replace("<br>", "\n")
    )
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if len(lines) <= 1:
        # Fallback: split by numbered list markers in a single long line
        parts = re.split(r"\s*(?=\d+[.)、]\s*)", normalized.strip())
        lines = [part.strip() for part in parts if part.strip()]
    items: list[str] = []
    for line in lines:
        cleaned = re.sub(r"^\d+[.)、]\s*", "", line).strip()
        if cleaned:
            items.append(cleaned)
    return items


def _to_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    if isinstance(value, str):
        return _split_text_to_items(value)
    return []


def _build_user_prompt(high_value_items: list[dict]) -> str:
    items_json = json.dumps(
        [
            {
                "url": r["url"],
                "title": r.get("hidden_signal") or r.get("title", ""),
                "core_event": r.get("core_event", ""),
                "score": round(r.get("score", 0), 2),
            }
            for r in high_value_items
        ],
        ensure_ascii=False,
        indent=2,
    )
    return f"""以下是今日经过初筛的高价值情报（score ≥ 0.85），共 {len(high_value_items)} 条：

{items_json}

请完成以下任务：
1. 对你认为值得深挖的条目（建议挑 3-5 条最重要的），使用 read_webpage 工具阅读原文完整内容，获得更深层理解。
2. 综合所有信息后，调用 submit_insights 提交最终报告：
   - trends: 宏观技术/行业趋势归纳，3-5 条，每条 ≤ 80 字
   - weak_signals: 潜藏的弱信号或暗流，2-4 条，每条 ≤ 80 字
   - daily_advices: 给工程师/独立开发者的今日行动建议，2-4 条，每条 ≤ 60 字

所有内容必须使用简体中文。"""


async def _run_agent(high_value_items: list[dict]) -> dict[str, Any] | None:
    try:
        from claude_agent_sdk import (  # type: ignore
            ClaudeAgentOptions,
            ClaudeSDKClient,
            create_sdk_mcp_server,
            tool,
        )
    except ImportError:
        print("[global_agent] claude-agent-sdk 未安装，跳过全局分析", flush=True)
        return None

    result_holder: dict[str, Any] = {}

    @tool(
        "read_webpage",
        "通过 Jina Reader 获取指定 URL 的干净正文 Markdown，用于深度阅读原文",
        {"url": str},
    )
    async def read_webpage(args: dict) -> dict:
        url = args["url"]
        jina_url = f"{JINA_READER_BASE}{url}"
        try:
            resp = _requests.get(
                jina_url,
                headers={"Accept": "text/plain", "x-respond-with": "markdown"},
                timeout=20,
            )
            resp.raise_for_status()
            content = resp.text[:JINA_MAX_CHARS]
        except Exception as e:
            content = f"[读取失败: {e}]"
        return {"content": [{"type": "text", "text": content}]}

    @tool(
        "submit_insights",
        "分析完成后，调用此工具提交最终结构化情报报告",
        {
            "type": "object",
            "properties": {
                "trends": {"type": "array", "items": {"type": "string"}},
                "weak_signals": {"type": "array", "items": {"type": "string"}},
                "daily_advices": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["trends", "weak_signals", "daily_advices"],
            "additionalProperties": False,
        },
    )
    async def submit_insights(args: dict) -> dict:
        try:
            parsed = GlobalInsightsReport.model_validate(args)
        except ValidationError as e:
            return {
                "content": [{"type": "text", "text": f"submit_insights 参数格式错误，请按数组字符串重提：{e}"}],
                "is_error": True,
            }
        result_holder.update(parsed.model_dump())
        return {"content": [{"type": "text", "text": "报告已收到，分析完毕。"}]}

    server = create_sdk_mcp_server(
        name="insights-tools",
        version="1.0.0",
        tools=[read_webpage, submit_insights],
    )

    allowed_tools = ["mcp__insights-tools__read_webpage", "mcp__insights-tools__submit_insights"]
    if GLOBAL_AGENT_ENABLE_SKILLS:
        allowed_tools.append("Skill")

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        allowed_tools=allowed_tools,
        mcp_servers={"insights-tools": server},
        permission_mode="acceptEdits",
        max_turns=30,
        cwd=Path.cwd(),
        setting_sources=["user", "project"] if GLOBAL_AGENT_ENABLE_SKILLS else None,
        output_format={
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "trends": {"type": "array", "items": {"type": "string"}},
                    "weak_signals": {"type": "array", "items": {"type": "string"}},
                    "daily_advices": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["trends", "weak_signals", "daily_advices"],
                "additionalProperties": False,
            },
        },
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(_build_user_prompt(high_value_items))
        async for _ in client.receive_response():
            pass

    return result_holder if result_holder else None


def run_global_analysis(
    analyses: dict[str, dict],
    candidates: list[dict],
    output_file: Path = GLOBAL_INSIGHTS_FILE,
) -> None:
    """
    从本次 pipeline 的分析结果中筛出高价值条目，
    驱动 Claude Agent 进行二次深度分析并写入 global_insights.json。
    """
    import anyio

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

    print(f"[global_agent] 启动全局 Agent 分析，共 {len(high_value)} 条高价值情报...", flush=True)

    result = anyio.run(_run_agent, high_value)

    if not result:
        print("[global_agent] Agent 未返回有效报告", flush=True)
        return

    output_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        parsed_report = GlobalInsightsReport.model_validate(result)
    except ValidationError as e:
        print(f"[global_agent] 报告格式校验失败: {e}", flush=True)
        return

    trends = parsed_report.trends
    weak_signals = parsed_report.weak_signals
    daily_advices = parsed_report.daily_advices
    if not trends and not weak_signals and not daily_advices:
        print(
            "[global_agent] 报告字段为空（可能返回了不兼容格式）",
            f"types={{trends:{type(result.get('trends')).__name__}, "
            f"weak_signals:{type(result.get('weak_signals')).__name__}, "
            f"daily_advices:{type(result.get('daily_advices')).__name__}}}",
            flush=True,
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_count": len(high_value),
        "trends": trends,
        "weak_signals": weak_signals,
        "daily_advices": daily_advices,
    }
    output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[global_agent] 全局分析完成，结果已写入 {output_file}", flush=True)
