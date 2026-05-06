"""
阶段 1.5 — 全文深化 Agent
对候选条目使用 Claude Agent SDK + Jina Reader(MCP Tool)
逐条读取原文全文，重新生成更高质量的 hidden_signal / core_event / actionable。
结果直接覆盖 analyses dict，供后续 pipeline 使用。

设计原则：
- 只精读通过粗筛的条目，不处理所有候选，控制时间和成本
- 有限并发（ENRICH_MAX_WORKERS），默认 5
- 使用 output_format 让 CLI 自动验证 JSON Schema（内置 5 次重试）
- 单条失败静默回退到原始粗筛结果
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

from rss2cubox.agent_sdk_runner import run_json_agent
from rss2cubox.webpage_reader import read_webpage_text

# 加载 .env 文件（本地开发时 .env 优先级最高，覆盖系统环境变量）
load_dotenv(override=True)

ENRICH_AGENT_ENABLED = os.getenv("ENRICH_AGENT_ENABLED", "true").lower() not in ("false", "0", "no")
ENRICH_MAX_WORKERS = max(1, int(os.getenv("ENRICH_MAX_WORKERS", "5")))
ENRICH_ITEM_TIMEOUT_SECONDS = max(10, int(os.getenv("ENRICH_ITEM_TIMEOUT_SECONDS", "90")))
ENRICH_ENABLE_SKILLS = os.getenv("ENRICH_ENABLE_SKILLS", "true").lower() in ("1", "true", "yes")
JINA_READER_BASE = os.getenv("JINA_READER_BASE", "https://r.jina.ai/")
JINA_MAX_CHARS = max(1000, int(os.getenv("JINA_MAX_CHARS", "30000")))
WECHAT_FETCH_TIMEOUT_SECONDS = max(10, int(os.getenv("WECHAT_FETCH_TIMEOUT_SECONDS", "30")))
_enrich_max_budget_raw = os.getenv("ENRICH_MAX_BUDGET_USD", "15.0").strip()
try:
    ENRICH_MAX_BUDGET_USD = float(_enrich_max_budget_raw) if _enrich_max_budget_raw else None
except ValueError:
    ENRICH_MAX_BUDGET_USD = None

# JSON Schema 用于 output_format（CLI 层自动验证）
ENRICH_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "core_event": {"type": "string", "maxLength": 100},
        "reason": {"type": "string", "maxLength": 120},
        "hidden_signal": {"type": "string", "maxLength": 200},
        "actionable": {"type": "string", "maxLength": 100},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "importance_score": {"type": "integer", "minimum": 1, "maximum": 5},
        "content_source": {"type": "string", "enum": ["full_text", "summary_only"]},
        "signal_type": {"type": "integer", "minimum": 1, "maximum": 12},
        "evidence_type": {"type": "integer", "minimum": 1, "maximum": 12},
        "evidence_strength": {"type": "integer", "minimum": 1, "maximum": 5},
        "novelty_score": {"type": "integer", "minimum": 1, "maximum": 5},
        "impact_horizon": {"type": "integer", "minimum": 1, "maximum": 5},
        "audience": {
            "type": "array",
            "items": {"type": "integer", "minimum": 1, "maximum": 8},
            "maxItems": 3,
        },
        "market_stage": {"type": "integer", "minimum": 1, "maximum": 6},
        "confidence": {"type": "integer", "minimum": 1, "maximum": 5},
        "entities": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "cluster_hint": {"type": "string", "maxLength": 60},
        "watch_keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "prediction": {"type": "string", "maxLength": 160},
        "disconfirming_evidence": {"type": "string", "maxLength": 160},
    },
    "required": [
        "core_event",
        "reason",
        "hidden_signal",
        "actionable",
        "tags",
        "importance_score",
        "content_source",
        "signal_type",
        "evidence_type",
        "evidence_strength",
        "novelty_score",
        "impact_horizon",
        "audience",
        "market_stage",
        "confidence",
        "entities",
        "cluster_hint",
        "watch_keywords",
        "prediction",
        "disconfirming_evidence",
    ],
}


SYSTEM_PROMPT = (
    "你是一位顶级科技产业分析师，尤其深耕 AI 与智能体（AI Agent）领域，正在对一篇已通过初筛的高价值文章进行深度精读。\n"
    "你已拥有文章的标题与初步摘要，但你必须先调用 read_webpage 工具获取原文全文，才能进行后续分析。\n"
    "（该工具优先走 Jina Reader 返回 Markdown；若目标站点屏蔽了 Jina，会自动降级到 Playwright 真实浏览器渲染。）\n"
    "【强制要求】在输出任何 JSON 分析结果之前，你必须先成功调用 read_webpage 获取并阅读完原文全文。\n"
    "如果 read_webpage 工具调用失败（即返回「网页读取失败」），你必须重试一次；若仍然失败，则输出 JSON 但 core_event、reason、hidden_signal、actionable 字段必须注明「原文读取失败，仅基于摘要」。\n"
    "阅读完毕后，直接以 JSON 格式输出分析结果。\n"
    "【关注重点】请特别留意以下方向的事件，在评分时适当体现其重要性：\n"
    "- AI 模型能力突破（新架构、新基准、Scaling Law 变化）\n"
    "- AI Agent / 智能体框架、工具链、多智能体协作\n"
    "- LLM 应用层创新（RAG、推理优化、长上下文、多模态）\n"
    "- 开源模型与生态动态（权重开源、微调方案、社区趋势）\n"
    "- AI 基础设施（算力、芯片、推理优化、训练框架）\n"
    "以上方向的信号在其他条件相同时应获得略高的 importance_score 和 novelty_score，但不要刻意拔高——仍需基于事实客观判断。\n"
    "【结构化稳定性要求】所有用于筛选的编码字段必须只输出整数或整数数组，不要输出中文枚举名、解释文本或\"3=开发者工作流\"这类混合字符串。\n"
    "字段要求：\n"
    "- core_event：冷静客观地用一句话描述事实（≤60字）\n"
    "- reason：简要说明这条信息为什么值得保留（≤60字）\n"
    "- hidden_signal：这意味着什么？背后的范式转移、行业冲击或深层技术含义（≤100字）\n"
    "- actionable：工程师/独立开发者应如何行动？（≤60字）\n"
    "- tags：输出 1-3 个精准标签，必须是字符串数组\n"
    "- importance_score：文章重要程度，1-5 分（1=一般资讯，2=值得关注，3=重要，4=非常重要，5=重大突破/必读）\n"
    "- content_source：必须注明本次分析的文本来源，值为「full_text」表示使用了全文，值为「summary_only」表示仅使用了摘要\n"
    "- signal_type：只输出数字。1=模型能力，2=基础设施/算力/芯片，3=开发者工作流，4=产品化/应用层，5=开源生态，6=研究论文/算法，7=安全/风险/对齐，8=监管/政策，9=商业/融资/组织动作，10=数据/评测/Benchmark，11=机器人/具身智能，12=其他\n"
    "- evidence_type：只输出数字。1=官方发布，2=论文/预印本，3=Benchmark/评测结果，4=代码仓库/开源项目，5=产品上线/功能发布，6=融资/并购/财报，7=招聘/组织调整，8=安全事件/事故，9=工程实践/技术博客，10=媒体报道，11=观点/评论，12=教程/二手整理\n"
    "- evidence_strength：只输出 1-5。1=弱，2=一般，3=中等，4=强，5=极强\n"
    "- novelty_score：只输出 1-5。1=已知延续，2=小幅变化，3=明显新动向，4=早期新范式，5=罕见/首次出现/可能开启新方向\n"
    "- impact_horizon：只输出数字。1=天级，2=周级，3=月级，4=季度级，5=年级\n"
    "- audience：输出 1-3 个数字。1=研究者，2=AI工程师，3=独立开发者，4=产品/创业者，5=投资/战略，6=政策/合规，7=安全团队，8=普通用户\n"
    "- market_stage：只输出数字。1=研究探索，2=Demo/实验，3=早期产品，4=工程化采用，5=规模化商业化，6=成熟基础设施\n"
    "- confidence：只输出 1-5。1=低，2=偏低，3=中，4=高，5=很高\n"
    "- entities：抽取公司、模型、框架、论文、数据集、Benchmark、产品等实体，最多 8 个\n"
    "- cluster_hint：用一个短语概括可聚类的信号主题（≤30字）\n"
    "- watch_keywords：后续追踪该信号的关键词，最多 8 个\n"
    "- prediction：如果该信号成立，未来 7/30/90 天应看到什么后续证据（≤80字）\n"
    "- disconfirming_evidence：什么后续现象会削弱或证伪该信号（≤80字）\n"
    "所有输出必须使用简体中文。"
)


def _build_user_prompt(item: dict, original: dict) -> str:
    return (
        f"文章标题：{item.get('title', '')}\n"
        f"原文链接：{item.get('url', '')}\n"
        f"初步摘要：{item.get('description', '')[:500]}\n"
        f"初步核心事件：{original.get('core_event', '')}\n\n"
        "步骤：\n"
        "1. 首先调用 read_webpage 工具读取原文全文（传入上方原文链接）。\n"
        "2. 仔细阅读完整内容后，再输出 JSON 格式的分析结果。\n"
        "3. content_source 字段必须如实填写：使用了全文填「full_text」，仅摘要则填「summary_only」。\n"
        "【强制】如果 read_webpage 返回「网页读取失败」，必须重试一次；重试仍失败则必须填写「summary_only」。"
    )


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
    return bool(payload and (payload.get("core_event") or payload.get("hidden_signal") or payload.get("reason")))


async def _enrich_one(item: dict, original: dict, log_event: Any | None = None) -> tuple[dict | None, str]:
    """
    使用 output_format 让 CLI 处理 JSON Schema 验证和重试。
    直接信任 structured_output，失败即返回错误。
    """
    import anyio

    try:
        from claude_agent_sdk import create_sdk_mcp_server, tool  # type: ignore
    except ImportError:
        return None, "claude_agent_sdk_import_error"

    expected_url = str(item.get("url", "")).strip()
    if not expected_url:
        return None, "missing_url"

    @tool(
        "read_webpage",
        "读取文章原文完整内容（优先 Jina Reader；Jina 被拦截时自动降级到 Playwright 浏览器渲染）",
        {"url": str},
    )
    async def read_webpage(args: dict) -> dict:
        def _fetch() -> tuple[bool, str]:
            return read_webpage_text(
                expected_url,
                jina_reader_base=JINA_READER_BASE,
                jina_max_chars=JINA_MAX_CHARS,
                wechat_timeout_seconds=WECHAT_FETCH_TIMEOUT_SECONDS,
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
    stderr_lines, stderr_logger = _make_stderr_logger(f"enrich_agent:{eid_short}")

    def sdk_logger(event: str, **fields: Any) -> None:
        if log_event is None:
            return
        level = "WARN" if event.endswith("_error") or event == "agent_sdk_no_result" else "INFO"
        log_event(
            level,
            event,
            stage="agent_sdk",
            agent="enrich",
            eid=item.get("eid", ""),
            url=expected_url,
            **fields,
        )

    try:
        structured_output = await run_json_agent(
            prompt=_build_user_prompt(item, original),
            system_prompt=SYSTEM_PROMPT,
            schema=ENRICH_OUTPUT_SCHEMA,
            allowed_tools=allowed_tools,
            mcp_servers={"enrich-tools": server},
            max_turns=10,
            max_budget_usd=ENRICH_MAX_BUDGET_USD,
            cwd=Path.cwd(),
            setting_sources=["project"] if ENRICH_ENABLE_SKILLS else None,
            stderr=stderr_logger,
            # 显式传递 ANTHROPIC_API_KEY 使 .env 拥有最高优先级
            env={k: v for k, v in os.environ.items() if k == "ANTHROPIC_API_KEY"},
            sdk_log=sdk_logger,
        )
        return structured_output, "ok"
    except Exception as e:
        if stderr_lines:
            print(f"[enrich_agent] eid={eid_short} error: {' | '.join(stderr_lines[-5:])}", flush=True)
        return None, str(e)

    return None, "no_result"


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
                enriched, reason = await _enrich_one(item, original, log_event)
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                if enriched:
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
                else:
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
        enrich_stats = anyio.run(_enrich_all, _enrich_candidates, analyses, log_event)
        log_event(
            "INFO",
            "enrich_complete",
            stage="enrich",
            enriched=enrich_stats.get("succeeded", 0),
            failed=enrich_stats.get("failed", 0),
            empty=enrich_stats.get("empty", 0),
            started=enrich_stats.get("started", len(_enrich_candidates)),
        )
    except Exception as e:
        log_event("WARN", "agent_analysis_error", stage="agent", error=str(e))
    return analyses
