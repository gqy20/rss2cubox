"""Claude Agent SDK powered Signal Cluster Agent."""
from __future__ import annotations

import json
import os
import re
from functools import partial
from datetime import datetime, timezone
from typing import Any

import anyio

from rss2cubox.agent_sdk_runner import _StructuredOutputError, _budget, extract_json_from_text, make_sdk_logger, run_json_agent, run_with_fallback


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
    "必须使用输入文章的 signal_type、cluster_hint、entities、watch_keywords、hidden_signal 和时间信息。"
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
    prompt = json.dumps(
        {
            "now": now_dt.isoformat(),
            "articles": articles,
            "existing_clusters": existing_clusters or [],
            "instructions": [
                "将相同或高度相关的长期信号归并为同一 cluster。",
                "每篇文章必须在 links 中出现且 article_id 必须来自输入。",
                "不要输出规则解释，只输出结构化 JSON。",
                "不要输出 recent_count_7d、previous_count_7d、burst_ratio、source_count、article_count。",
            ],
        },
        ensure_ascii=False,
    )

    sdk_logger = make_sdk_logger("signal_cluster", log_event=log_event,
                                article_count=len(articles),
                                existing_cluster_count=len(existing_clusters or []))

    payload = anyio.run(
        partial(
            run_with_fallback,
            partial(
                run_json_agent,
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
                schema=SIGNAL_CLUSTER_OUTPUT_SCHEMA,
                max_turns=200,
                max_budget_usd=_budget("SIGNAL_CLUSTER_AGENT_MAX_BUDGET_USD", 10.0),
                sdk_log=sdk_logger,
            ),
            agent_name="signal_cluster",
            validate=lambda d: isinstance(d.get("clusters"), list),
            sdk_log=log_event,
        )
    )

    return _validate_payload(payload, {str(article["id"]) for article in articles if article.get("id")})


def _validate_payload(payload: dict[str, Any], article_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    clusters = payload.get("clusters")
    links = payload.get("links")
    if not isinstance(clusters, list) or not isinstance(links, list):
        raise RuntimeError("invalid_signal_cluster_payload")

    cluster_keys = {str(cluster.get("cluster_key")) for cluster in clusters if cluster.get("cluster_key")}
    # 过滤无效 link 而非丢弃全部结果
    valid_links = []
    for link in links:
        aid = str(link.get("article_id", ""))
        ckey = str(link.get("cluster_key", ""))
        if aid and aid in article_ids and ckey and ckey in cluster_keys:
            valid_links.append(link)
    return {"clusters": clusters, "links": valid_links}

# _budget 已抽取到 agent_sdk_runner._budget
