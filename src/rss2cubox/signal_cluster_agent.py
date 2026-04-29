"""Claude Agent SDK powered Signal Cluster Agent."""
from __future__ import annotations

import json
import os
import re
from functools import partial
from datetime import datetime, timezone
from typing import Any

import anyio

from rss2cubox.agent_sdk_runner import run_json_agent


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
                    "article_count": {"type": "integer", "minimum": 1},
                    "source_count": {"type": "integer", "minimum": 0},
                    "avg_importance": {"type": "number"},
                    "avg_evidence_strength": {"type": "number"},
                    "avg_novelty": {"type": "number"},
                    "avg_confidence": {"type": "number"},
                    "recent_count_7d": {"type": "integer", "minimum": 0},
                    "previous_count_7d": {"type": "integer", "minimum": 0},
                    "burst_ratio": {"type": "number"},
                },
                "required": [
                    "cluster_key", "label", "normalized_label", "signal_type", "status",
                    "summary", "entities", "watch_keywords", "first_seen_at", "last_seen_at",
                    "article_count", "source_count", "avg_importance", "avg_evidence_strength",
                    "avg_novelty", "avg_confidence", "recent_count_7d", "previous_count_7d",
                    "burst_ratio",
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
)


def normalize_cluster_label(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "unknown"


def build_cluster_key(article: dict[str, Any]) -> str:
    signal_type = article.get("signal_type")
    if not isinstance(signal_type, int) or signal_type < 1:
        signal_type = 12
    raw_label = str(article.get("cluster_hint") or article.get("title") or "unknown").strip()
    return f"{signal_type}:{normalize_cluster_label(raw_label)}"


def run_signal_cluster_agent(
    articles: list[dict[str, Any]],
    *,
    existing_clusters: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
    log_event: Any | None = None,
) -> dict[str, list[dict[str, Any]]]:
    if not articles:
        return {"clusters": [], "links": []}

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
            ],
        },
        ensure_ascii=False,
    )

    def sdk_logger(event: str, **fields: Any) -> None:
        if log_event is None:
            return
        level = "WARN" if event.endswith("_error") or event == "agent_sdk_no_result" else "INFO"
        log_event(
            level,
            event,
            stage="agent_sdk",
            agent="signal_cluster",
            article_count=len(articles),
            existing_cluster_count=len(existing_clusters or []),
            **fields,
        )

    payload = anyio.run(partial(
        run_json_agent,
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT,
        schema=SIGNAL_CLUSTER_OUTPUT_SCHEMA,
        max_turns=20,
        max_budget_usd=_budget("SIGNAL_CLUSTER_AGENT_MAX_BUDGET_USD", 10.0),
        sdk_log=sdk_logger,
    ))
    return _validate_payload(payload, {str(article["id"]) for article in articles if article.get("id")})


def _validate_payload(payload: dict[str, Any], article_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    clusters = payload.get("clusters")
    links = payload.get("links")
    if not isinstance(clusters, list) or not isinstance(links, list):
        raise RuntimeError("invalid_signal_cluster_payload")

    cluster_keys = {str(cluster.get("cluster_key")) for cluster in clusters if cluster.get("cluster_key")}
    for link in links:
        if str(link.get("article_id")) not in article_ids:
            raise RuntimeError("signal_cluster_link_unknown_article")
        if str(link.get("cluster_key")) not in cluster_keys:
            raise RuntimeError("signal_cluster_link_unknown_cluster")
    return {"clusters": clusters, "links": links}


def _budget(name: str, default: float) -> float | None:
    raw = os.getenv(name, str(default)).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return default
