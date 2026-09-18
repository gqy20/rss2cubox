"""
每日日报生成 Agent。

从 articles / global_insights / signal_clusters / trend_predictions 四张表聚合当日数据，
使用 Claude Agent SDK 生成结构化日报，写入 daily_reports 表。

设计原则：
- 摘要塞 prompt + 完整数据走 Read 工具（控制 token 成本）
- 支持 read_webpage 核实关键信息
- 通过 DAILY_REPORT_ENABLED=false 关闭
- 复用 prediction_loop_runner 的 _stage_due 频率控制模式
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from rss2cubox.prompt_registry import get, param

load_dotenv(override=True)

# ENABLED / ENABLE_SKILLS 是部署开关（env-only）；数值型运行参数走
# param 三层解析：.env 环境变量 > prompts/daily_report.yaml params > 代码默认值。
DAILY_REPORT_ENABLED = os.getenv("DAILY_REPORT_ENABLED", "true").lower() not in ("false", "0", "no")
DAILY_REPORT_ENABLE_SKILLS = os.getenv("DAILY_REPORT_ENABLE_SKILLS", "true").lower() in ("1", "true", "yes")
DAILY_REPORT_INTERVAL_HOURS = param("daily_report", "interval_hours", 24, env_var="DAILY_REPORT_INTERVAL_HOURS", minimum=1)
DAILY_REPORT_MAX_BUDGET_USD = param("daily_report", "max_budget_usd", 50.0, env_var="DAILY_REPORT_MAX_BUDGET_USD")

# system_prompt / 输出 schema 集中在项目根 prompts/daily_report.yaml
#（signal_item / top_article 等子 schema 在 yml 里用锚点复用）。
_PROMPT = get("daily_report")

SYSTEM_PROMPT = _PROMPT.system_prompt

# JSON Schema 用于 output_format（CLI 层自动验证）
DAILY_REPORT_OUTPUT_SCHEMA = _PROMPT.output_schema


# _normalize_signal_item 已迁移到 agent_sdk_runner.normalize_signal_item（enable_comment=True, max_text_length=300）


def _collect_day_data(report_date: str) -> dict[str, Any]:
    """
    从 4 张表聚合当日数据。

    返回包含以下 key 的 dict：
    - report_date
    - today_articles_summary (统计 + TOP 文章)
    - today_global_insights (原始 insights 列表)
    - cluster_snapshot (活跃簇 + 变化)
    - prediction_status (待验证预测 + 近期评审)
    """
    from rss2cubox.db_client import (
        get_articles_by_date,
        get_all_global_insights,
        get_existing_signal_clusters,
        get_due_trend_predictions,
        get_recent_prediction_reviews,
        get_fulltexts_by_eids,
    )

    # 解析日期范围
    try:
        dt = datetime.strptime(report_date, "%Y-%m-%d")
        day_start = dt.replace(tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        yesterday_start = day_start - timedelta(days=1)
    except ValueError:
        day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        yesterday_start = day_start - timedelta(days=1)
        report_date = day_start.strftime("%Y-%m-%d")

    result: dict[str, Any] = {"report_date": report_date}

    # ── 1. 今日文章 ────────────────────────────────
    all_articles = get_articles_by_date(
        start_date=report_date,
        end_date=report_date,
        limit=500,
    )

    high_importance = [a for a in all_articles if isinstance(a.get("importance_score"), int) and a["importance_score"] >= 4]
    sorted_by_importance = sorted(all_articles, key=lambda a: a.get("importance_score", 0), reverse=True)
    top_15 = sorted_by_importance[:15]

    # 批量获取预抓取全文
    _article_ids = [a.get("id", "") for a in top_15 if a.get("id")]
    _ft_map = get_fulltexts_by_eids(_article_ids) if _article_ids else {}

    top_articles = []
    for a in top_15:
        top_articles.append({
            "title": a.get("title", ""),
            "url": a.get("url", ""),
            "source_feed_name": a.get("source_feed_name", ""),
            "importance_score": a.get("importance_score", 3),
            "hidden_signal": a.get("hidden_signal", ""),
            "full_text": _ft_map.get(a.get("id", ""), "") or "",
        })

    # feed 来源分布
    feed_counts: dict[str, int] = {}
    for a in all_articles:
        name = a.get("source_feed_name", "unknown") or "unknown"
        feed_counts[name] = feed_counts.get(name, 0) + 1

    result["today_articles_summary"] = {
        "total_articles": len(all_articles),
        "high_importance_count": len(high_importance),
        "feed_sources": dict(sorted(feed_counts.items(), key=lambda x: x[1], reverse=True)[:10]),
        "top_articles": top_articles,
    }

    # ── 2. 今日全局洞察 ──────────────────────────
    all_insights = get_all_global_insights(limit=50)
    today_insights = []
    for ins in all_insights:
        gen_at = ins.get("generated_at", "")
        if isinstance(gen_at, str):
            try:
                ins_dt = datetime.fromisoformat(gen_at)
                if ins_dt.tzinfo is None:
                    ins_dt = ins_dt.replace(tzinfo=timezone.utc)
                if day_start <= ins_dt < day_end:
                    today_insights.append(ins)
            except (ValueError, TypeError):
                pass
        elif hasattr(gen_at, "astimezone"):
            if day_start <= gen_at < day_end:
                today_insights.append(ins)

    result["today_global_insights"] = today_insights

    # ── 3. 信号簇快照 ────────────────────────────
    all_clusters = get_existing_signal_clusters(limit=100)

    active_clusters = []
    for c in all_clusters:
        last_seen = c.get("last_seen_at")
        if last_seen is None:
            continue
        if isinstance(last_seen, str):
            try:
                last_dt = datetime.fromisoformat(last_seen)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                # 最近 3 天有更新的视为活跃
                if last_dt >= yesterday_start:
                    active_clusters.append(c)
            except (ValueError, TypeError):
                pass
        elif hasattr(last_seen, "astimezone"):
            if last_seen >= yesterday_start:
                active_clusters.append(c)

    result["cluster_snapshot"] = {
        "active_clusters": active_clusters,
        "cluster_evolution": [],  # Agent 可基于此自行分析变化
    }

    # ── 4. 预测状态 ──────────────────────────────
    pending_preds = get_due_trend_predictions(limit=20)
    recent_reviews = get_recent_prediction_reviews(limit=15)

    result["prediction_status"] = {
        "pending_predictions": pending_preds,
        "recent_reviews": recent_reviews,
    }

    return result


def _prepare_temp_files(day_data: dict[str, Any]) -> dict[str, str]:
    """将完整数据写入临时文件，返回 {name: path} 映射。"""
    from rss2cubox.agent_sdk_runner import write_temp_json

    return {
        "articles": write_temp_json(day_data.get("today_articles_summary", {}).get("top_articles", [])),
        "insights": write_temp_json(day_data.get("today_global_insights", [])),
        "clusters": write_temp_json(day_data.get("cluster_snapshot", {}).get("active_clusters", [])),
        "predictions": write_temp_json(day_data.get("prediction_status", {})),
    }


async def _run_agent(
    day_data: dict[str, Any],
    log_event: Any | None = None,
) -> dict[str, Any] | None:
    """执行日报 Agent 分析，最多重试 3 次。"""
    import anyio

    try:
        from claude_agent_sdk import create_sdk_mcp_server, tool
    except ImportError:
        print("[daily_report] claude-agent-sdk 未安装，跳过日报生成", flush=True)
        return None

    from rss2cubox.agent_sdk_runner import (
        _StructuredOutputError,
        _agent_timeout,
        cleanup_temp_files,
        extract_json_from_text,
        create_read_webpage_mcp,
        get_jina_config,
        make_sdk_logger,
        make_stderr_logger,
        normalize_signal_item,
        run_json_agent,
    )

    temp_files = _prepare_temp_files(day_data)
    file_paths_to_cleanup = list(temp_files.values())

    summary = day_data.get("today_articles_summary", {})
    cluster_snap = day_data.get("cluster_snapshot", {})
    pred_status = day_data.get("prediction_status", {})

    user_prompt = (
        f"请基于以下数据生成 {day_data['report_date']} 的日报。\n\n"
        f"## 数据文件\n"
        f"- 今日高重要性文章（按重要性排序）：{temp_files['articles']}\n"
        f"- 今日全局洞察（{len(day_data.get('today_global_insights', []))}次分析）：{temp_files['insights']}\n"
        f"- 信号簇状态（{len(cluster_snap.get('active_clusters', []))}个活跃簇）：{temp_files['clusters']}\n"
        f"- 预测跟踪：{temp_files['predictions']}\n\n"

        f"## 快速概览\n"
        f"- 文章总数：{summary.get('total_articles', 0)}篇，"
        f"高重要性：{summary.get('high_importance_count', 0)}篇\n"
        f"- 活跃信号簇：{len(cluster_snap.get('active_clusters', []))}个\n"
        f"- 待验证预测：{len(pred_status.get('pending_predictions', []))}个\n"
        f"- 近期命中评审：{sum(1 for r in pred_status.get('recent_reviews', []) if r.get('hit_level') == 'hit')}个\n\n"

        f"请先 Read 数据文件了解全貌，再选择性 read_webpage 深入核实。\n\n"

        f"【输出要求】完成分析后直接输出结构化 JSON 格式的日报，必须包含以下所有字段：\n"
        f"- summary: 统计摘要（total_articles, high_importance_count, insights_generated_today, active_clusters, pending_predictions, recent_hit_reviews, top_feeds）\n"
        f"- trends: 宏观技术/行业趋势归纳，3-8条，每条 {{text, source_urls, source_titles, comment}}\n"
        f"- weak_signals: 潜藏弱信号或暗流，2-5条\n"
        f"- daily_advices: 今日行动建议，2-5条\n"
        f"- top_articles: 重要文章列表，5-10条，每条含 title/url/importance_score/comment\n"
        f"- cluster_evolution: 值得关注的信号簇变化\n"
        f"- prediction_status: 即将到期预测的关注建议\n"
        f"- key_topics: 核心主题标签 3-6 个\n"
        f"- confidence_level: \"high\" / \"medium\" / \"low\"\n"
        f"即使某类数据为空，该字段也必须作为空数组 [] 存在，不得省略任何字段。不要发明 schema 中不存在的字段名。\n\n"

        f"注意：高重要性文章数据中已附带「full_text」预抓取全文字段，可直接使用；如需更新内容可调用 read_webpage。"
    )

    stderr_lines, stderr_logger = make_stderr_logger("daily_report", limit=80)

    sdk_logger = make_sdk_logger("daily_report", log_event=log_event, prompt_version=_PROMPT.version)

    max_retries = 3
    last_error: str | None = None

    for attempt in range(max_retries):
        # 每次重试需要重新创建 MCP server（run_json_agent 每次创建新 session）
        server, read_webpage_tool_name = create_read_webpage_mcp("daily-report-tools")

        allowed_tools = [
            read_webpage_tool_name,
            "Read",
            "Grep",
            "Glob",
        ]
        if DAILY_REPORT_ENABLE_SKILLS:
            allowed_tools.append("Skill")

        if attempt > 0:
            print(f"[daily_report] 重试第 {attempt}/{max_retries - 1} 次 (上次错误: {last_error})", flush=True)
            if log_event:
                log_event("WARN", "daily_report_retry", retry_index=attempt, last_error=last_error or "")

        try:
            structured_output = await run_json_agent(
                prompt=user_prompt,
                system_prompt=SYSTEM_PROMPT,
                schema=DAILY_REPORT_OUTPUT_SCHEMA,
                allowed_tools=allowed_tools,
                mcp_servers={"daily-report-tools": server},
                max_turns=param("daily_report", "max_turns", 200),
                max_budget_usd=DAILY_REPORT_MAX_BUDGET_USD,
                timeout_seconds=_agent_timeout(
                    "DAILY_REPORT_AGENT_TIMEOUT_SECONDS",
                    default=param("daily_report", "timeout_seconds", 1800),
                    minimum=120,
                ),
                cwd=Path.cwd(),
                setting_sources=["project"] if DAILY_REPORT_ENABLE_SKILLS else None,
                stderr=stderr_logger,
                sdk_log=sdk_logger,
            )
            result = {
                "report_date": day_data["report_date"],
                "generated_at": datetime.now(timezone.utc).isoformat(),
                **structured_output,
            }
            print(f"[daily_report] Agent 完成 (第{attempt + 1}次尝试)", flush=True)
            return result
        except _StructuredOutputError as e:
            print(f"[daily_report] structured_output 为空，尝试 fallback... (第{attempt + 1}次)", flush=True)
            fallback = extract_json_from_text(e.raw_text)
            _FALLBACK_REQUIRED = {"trends", "weak_signals", "daily_advices"}
            if fallback and isinstance(fallback, dict) and _FALLBACK_REQUIRED.issubset(fallback.keys()):
                result = {
                    "report_date": day_data["report_date"],
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    **fallback,
                }
                print(f"[daily_report] fallback 成功 (第{attempt + 1}次)", flush=True)
                return result
            if fallback and isinstance(fallback, dict):
                missing = _FALLBACK_REQUIRED - set(fallback.keys())
                print(f"[daily_report] fallback 缺少必需字段 {missing}，继续重试", flush=True)
            else:
                print(f"[daily_report] fallback 也失败: {e.raw_text[:300]}", flush=True)
            last_error = f"structured_output_fallback_failed: missing required fields"
        except TimeoutError as exc:
            last_error = f"TimeoutError after {_agent_timeout('DAILY_REPORT_AGENT_TIMEOUT_SECONDS', default=param('daily_report', 'timeout_seconds', 1800), minimum=120)}s"
            print(f"[daily_report] 超时 (第{attempt + 1}次): {last_error}", flush=True)
        except RuntimeError as exc:
            last_error = str(exc) or type(exc).__name__
            print(f"[daily_report] 运行时错误 (第{attempt + 1}次): {last_error}", flush=True)
        except Exception as exc:
            last_error = str(exc) or type(exc).__name__
            print(f"[daily_report] 异常 (第{attempt + 1}次): {last_error}", flush=True)
            # 非预期异常不重试，直接退出
            break

    print(f"[daily_report] 已耗尽全部 {max_retries} 次尝试，最终错误: {last_error}", flush=True)
    if log_event:
        log_event("WARN", "daily_report_all_retries_exhausted", attempts=max_retries, last_error=last_error or "")
    cleanup_temp_files(*file_paths_to_cleanup)
    return None


def run_daily_report(log_event: Any | None = None) -> dict[str, Any] | None:
    """
    日报生成入口函数。

    流程：
    1. 检查是否启用
    2. 聚合当日数据
    3. 调用 Agent 生成报告
    4. 返回 payload（由调用方写入 DB）
    """
    if not DAILY_REPORT_ENABLED:
        print("[daily_report] DAILY_REPORT_ENABLED=false，跳过", flush=True)
        return None

    report_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if log_event:
        log_event("INFO", "daily_report_start", report_date=report_date)

    # 聚合数据
    try:
        day_data = _collect_day_data(report_date)
    except Exception as e:
        if log_event:
            log_event("WARN", "daily_report_collect_failed", error=str(e))
        print(f"[daily_report] 数据聚合失败: {e}", flush=True)
        return None

    article_count = day_data.get("today_articles_summary", {}).get("total_articles", 0)
    insights_count = len(day_data.get("today_global_insights", []))

    # 最小阈值检查：没有新文章也没有洞察时跳过
    if article_count == 0 and insights_count == 0:
        print("[daily_report] 无数据（0 文章 + 0 洞察），跳过", flush=True)
        if log_event:
            log_event("INFO", "daily_report_skipped", reason="no_data")
        return None

    print(f"[daily_report] 开始生成日报: {report_date}, 文章={article_count}, 洞察={insights_count}", flush=True)

    # 执行 Agent
    import anyio
    try:
        result = anyio.run(_run_agent, day_data, log_event)
        if result and log_event:
            total_items = (
                len(result.get("trends", []))
                + len(result.get("weak_signals", []))
                + len(result.get("daily_advices", []))
            )
            log_event("INFO", "daily_report_done", items=total_items)
        return result
    except Exception as e:
        if log_event:
            log_event("WARN", "daily_report_agent_failed", error=str(e))
        print(f"[daily_report] Agent 执行失败: {e}", flush=True)
        return None
