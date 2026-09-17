"""Claude Agent SDK powered Signal Cluster Agent."""
from __future__ import annotations

import json
import os
import re
from functools import partial
from datetime import datetime, timezone
from typing import Any

import anyio

from rss2cubox.agent_sdk_runner import (
    _StructuredOutputError,
    _agent_timeout,
    _budget,
    cleanup_temp_files,
    extract_json_from_text,
    make_sdk_logger,
    run_json_agent,
    run_with_fallback,
    write_temp_jsonl,
)


SIGNAL_CLUSTER_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cluster_key": {"type": "string"},
                    "label": {"type": "string"},
                    "normalized_label": {"type": "string"},
                    "signal_type": {"type": "integer", "minimum": 1, "maximum": 12},
                    "status": {"type": "string", "enum": ["new", "warming", "bursting", "cooling", "mature", "invalid"]},
                    "summary": {"type": "string"},
                    "entities": {"type": "array", "items": {"type": "string"}},
                    "watch_keywords": {"type": "array", "items": {"type": "string"}},
                    "first_seen_at": {"type": "string"},
                    "last_seen_at": {"type": "string"},
                    "avg_importance": {"type": "number"},
                    "avg_confidence": {"type": "number"},
                },
                "required": [
                    "cluster_key", "label", "normalized_label", "signal_type", "status",
                    "summary", "entities", "watch_keywords",
                ],
            },
        },
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cluster_key": {"type": "string"},
                    "article_id": {"type": "string"},
                    "relevance_score": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["cluster_key", "article_id", "relevance_score"],
            },
        },
    },
    "required": ["clusters", "links"],
}


SYSTEM_PROMPT = (
    "你是 Signal Cluster Agent，负责把已结构化 enrich 的文章归并为长期 AI 发展信号簇。"
    "输入给出全部文章的索引（ref/标题/聚类提示/实体/关键词/重要度/信号类型/日期），"
    "索引已覆盖所有文章，分组应主要依据索引。hidden_signal 等更细的字段在明细文件里，"
    "只在索引不足以判断某一篇归属时按 ref 精确 Grep，且次数受限——不要通读整个文件。"
    "不要做 embedding，不要臆造不存在的文章。输出必须符合 JSON Schema。"
    "cluster_key 必须稳定，格式为 '<signal_type>:<normalized_label>'。"
    "status 只能是 new、warming、bursting、cooling、mature、invalid。"
    "只输出 cluster_key、label、normalized_label、signal_type、status、summary、entities、watch_keywords "
    "以及可选的 first_seen_at、last_seen_at、avg_importance、avg_confidence。"
    "不要输出 recent_count_7d、previous_count_7d、burst_ratio、source_count 等字段。"
)


def normalize_cluster_label(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^\w一-鿿-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "unknown"


def build_cluster_key(article: dict[str, Any]) -> str:
    signal_type = article.get("signal_type")
    if not isinstance(signal_type, int) or signal_type < 1:
        signal_type = 12
    raw_label = str(article.get("cluster_hint") or article.get("title") or "unknown").strip()
    return f"{signal_type}:{normalize_cluster_label(raw_label)}"


SIGNAL_CLUSTER_MAX_ARTICLES = max(10, int(os.getenv("SIGNAL_CLUSTER_MAX_ARTICLES", "200")))
# 索引在 prompt 里、明细在文件里。这两个值限制 agent 翻文件的次数，
# 防止重蹈 daily_report 的覆辙（max_turns=200 → 实跑 25 轮 → 798K input tokens）。
SIGNAL_CLUSTER_MAX_TURNS = max(3, int(os.getenv("SIGNAL_CLUSTER_MAX_TURNS", "12")))
SIGNAL_CLUSTER_MAX_DETAIL_READS = max(0, int(os.getenv("SIGNAL_CLUSTER_MAX_DETAIL_READS", "5")))


def _build_index(
    articles: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    """拆成「进 prompt 的索引」+「写文件的明细」，返回 (索引, ref→真实id, 明细)。

    ref 用 a001 这种短序号而不是截断的 sha256：
    - 4 字符 vs 64 字符，200 篇约省 4,000 input tokens 与 2,600 output tokens
    - 序号不会碰撞，截断哈希理论上会
    - 回映只是 dict 查表，且能校验模型有没有编造 ref
    """
    index_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    ref_to_id: dict[str, str] = {}
    for i, article in enumerate(articles, start=1):
        ref = f"a{i:03d}"
        real_id = str(article.get("id") or "")
        ref_to_id[ref] = real_id
        index_rows.append({
            "ref": ref,
            "title": str(article.get("title") or "")[:160],
            "hint": str(article.get("cluster_hint") or "")[:80],
            "entities": [str(x)[:40] for x in (article.get("entities") or [])][:6],
            "keywords": [str(x)[:30] for x in (article.get("watch_keywords") or [])][:6],
            "imp": article.get("importance_score"),
            "sig": article.get("signal_type"),
            "date": str(article.get("publish_time") or "")[:10],
        })
        detail: dict[str, Any] = {"ref": ref, "id": real_id}
        for key in ("title", "cluster_hint", "entities", "watch_keywords", "hidden_signal",
                    "reason", "actionable", "signal_type", "evidence_type", "evidence_strength",
                    "novelty_score", "impact_horizon", "market_stage", "confidence",
                    "importance_score", "publish_time", "source_feed_name", "url"):
            if key in article:
                detail[key] = article[key]
        detail_rows.append(detail)
    return index_rows, ref_to_id, detail_rows


def run_signal_cluster_agent(
    articles: list[dict[str, Any]],
    *,
    existing_clusters: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
    log_event: Any | None = None,
) -> dict[str, list[dict[str, Any]]]:
    if not articles:
        return {"clusters": [], "links": []}

    # 按 importance_score 降序预筛，保留高价值文章
    articles.sort(key=lambda a: a.get("importance_score", 0), reverse=True)
    articles = articles[:SIGNAL_CLUSTER_MAX_ARTICLES]

    now_dt = now or datetime.now(timezone.utc)
    index_rows, ref_to_id, detail_rows = _build_index(articles)
    detail_path = write_temp_jsonl(detail_rows)

    prompt = (
        f"共有 {len(articles)} 篇候选文章，当前时间 {now_dt.isoformat()}。\n\n"
        f"【索引】下面是**全部 {len(articles)} 篇**的索引"
        "（ref / 标题 / 聚类提示 / 实体 / 关键词 / 重要度 / 信号类型 / 日期）。\n"
        "索引已经覆盖所有文章，归并分组的判断请**主要依据索引**：\n"
        f"{json.dumps(index_rows, ensure_ascii=False)}\n\n"
        f"【明细文件】完整明细在 {detail_path}\n"
        '（JSONL 格式，每行一篇文章，行内含 "ref" 字段）。\n'
        "只在索引信息不足以判断某一篇的归属时，才用 Grep 按 ref 精确取那一行，例如：\n"
        f'    Grep  pattern=\'"ref": "a017"\'  path={detail_path}\n'
        f"**最多 {SIGNAL_CLUSTER_MAX_DETAIL_READS} 次**。\n"
        "不要 Read 整个文件，也不要逐篇读取 —— 索引已经是完整的，翻文件只会浪费轮次。\n\n"
        "【已有簇】\n"
        f"{json.dumps(existing_clusters or [], ensure_ascii=False)}\n\n"
        "【输出要求】\n"
        "1. 将相同或高度相关的长期信号归并为同一 cluster。\n"
        "2. links 必须为索引里的**每一篇**文章输出一条，含 cluster_key / article_id / "
        "relevance_score 三个字段。article_id 填索引里的 ref（例如 a017），不要填别的形式。"
        "覆盖率会被程序校验，漏掉的文章会被记为未归类并告警。\n"
        "3. 不要输出规则解释，只输出结构化 JSON。\n"
        "4. 不要输出 recent_count_7d、previous_count_7d、burst_ratio、source_count、article_count。"
    )

    sdk_logger = make_sdk_logger("signal_cluster", log_event=log_event,
                                article_count=len(articles),
                                existing_cluster_count=len(existing_clusters or []),
                                prompt_chars=len(prompt),
                                detail_path=detail_path)

    try:
        payload = anyio.run(
            partial(
                run_with_fallback,
                partial(
                    run_json_agent,
                    prompt=prompt,
                    system_prompt=SYSTEM_PROMPT,
                    schema=SIGNAL_CLUSTER_OUTPUT_SCHEMA,
                    allowed_tools=["Read", "Grep", "Glob"],
                    max_turns=SIGNAL_CLUSTER_MAX_TURNS,
                    max_budget_usd=_budget("SIGNAL_CLUSTER_AGENT_MAX_BUDGET_USD", 10.0),
                    timeout_seconds=_agent_timeout("SIGNAL_CLUSTER_AGENT_TIMEOUT_SECONDS", default=900, minimum=120),
                    setting_sources=None,
                    sdk_log=sdk_logger,
                ),
                agent_name="signal_cluster",
                validate=lambda d: isinstance(d.get("clusters"), list),
                sdk_log=log_event,
            )
        )
    finally:
        cleanup_temp_files(detail_path)

    real_ids = {str(a["id"]) for a in articles if a.get("id")}
    result = _validate_payload(payload, real_ids, ref_to_id=ref_to_id)

    # links 覆盖率必须显式告警。上一次运行 links 返回空数组，13 个簇全部
    # article_count=0、signal_cluster_articles 空表，但整条链路没有任何告警，
    # 是查数据库时才发现的 —— "成功"的事件路径掩盖了空结果。
    coverage = (len(result["links"]) / len(articles)) if articles else 0.0
    if log_event:
        log_event(
            "INFO" if coverage >= 0.8 else "WARN",
            "signal_cluster_link_coverage",
            stage="cluster",
            articles=len(articles),
            links=len(result["links"]),
            clusters=len(result["clusters"]),
            coverage=round(coverage, 3),
            unmapped=result.get("unmapped_refs", 0),
        )
    return result


def _validate_payload(
    payload: dict[str, Any],
    article_ids: set[str],
    *,
    ref_to_id: dict[str, str] | None = None,
) -> dict[str, Any]:
    clusters = payload.get("clusters")
    links = payload.get("links")
    if not isinstance(clusters, list) or not isinstance(links, list):
        raise RuntimeError("invalid_signal_cluster_payload")

    refs = ref_to_id or {}
    cluster_keys = {str(c.get("cluster_key")) for c in clusters if c.get("cluster_key")}
    # 过滤无效 link 而非丢弃全部结果。article_id 同时接受 ref（a001）和真实 id：
    # 模型可能回显索引里的 ref，也可能吐出明细文件里的真实 id，两种都要能落地。
    valid_links: list[dict[str, Any]] = []
    unmapped = 0
    seen_pairs: set[tuple[str, str]] = set()
    for link in links:
        if not isinstance(link, dict):
            unmapped += 1
            continue
        raw = str(link.get("article_id", "")).strip()
        aid = refs.get(raw, raw)
        ckey = str(link.get("cluster_key", "")).strip()
        if not aid or aid not in article_ids or not ckey or ckey not in cluster_keys:
            unmapped += 1
            continue
        pair = (ckey, aid)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        valid_links.append({**link, "article_id": aid, "cluster_key": ckey})
    return {"clusters": clusters, "links": valid_links, "unmapped_refs": unmapped}

# _budget 已抽取到 agent_sdk_runner._budget
