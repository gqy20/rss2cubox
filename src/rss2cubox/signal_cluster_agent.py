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
                    "signal_type": {"type": "integer", "minimum": 1, "maximum": 12, "description": "固定分类编号，有效范围 1~12（12=噪声/与AI无关）。绝不能编造范围外的编号"},
                    "status": {"type": "string", "enum": ["new", "warming", "bursting", "cooling", "mature", "invalid"]},
                    "summary": {"type": "string"},
                    "entities": {"type": "array", "items": {"type": "string"}},
                    "watch_keywords": {"type": "array", "items": {"type": "string"}},
                    "first_seen_at": {"type": "string"},
                    "last_seen_at": {"type": "string"},
                    # avg_importance / avg_confidence 已从模型输出中移除：
                    # save_signal_clusters 从真实文章 SQL 聚合，模型给的值从不被使用。
                    # 实测模型在 0~1 与 0~1000 刻度间摇摆，23 次结构化重试全因它。
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
    "required": ["clusters"],
}


SYSTEM_PROMPT = (
    "你是 Signal Cluster Agent，负责把已结构化 enrich 的文章归并为长期 AI 发展信号簇。"
    "输入给出全部文章的索引（ref/标题/聚类提示/实体/关键词/重要度/信号类型/日期），"
    "索引已覆盖所有文章，分组应主要依据索引。hidden_signal 等更细的字段在明细文件里，"
    "只在索引不足以判断某一篇归属时按 ref 精确 Grep，且次数受限——不要通读整个文件。"
    "不要做 embedding，不要臆造不存在的文章。输出必须符合 JSON Schema。"
    "cluster_key 必须稳定，格式为 '<signal_type>:<normalized_label>'。"
    "** signal_type 是固定分类编号，有效范围 1~12，参考索引里的 sig 字段；"
    "12 表示噪声/与 AI 无关。绝不能编造 13、14 之类的新编号。**"
    "status 只能是 new、warming、bursting、cooling、mature、invalid。"
    "只输出 cluster_key、label、normalized_label、signal_type、status、summary、entities、watch_keywords "
    "以及可选的 first_seen_at、last_seen_at。聚合评分（avg_importance 等）由程序从真实文章计算，不要输出。"
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
# 轮数上限。不用 200（daily_report 就是 200，实跑 25 轮烧掉 798K input tokens），
# 但也不能压到个位数：聚类需要对拿不准的文章去翻明细，压太死等于禁止深入。
SIGNAL_CLUSTER_MAX_TURNS = max(3, int(os.getenv("SIGNAL_CLUSTER_MAX_TURNS", "30")))
# links 覆盖率低于此值就重试一次。实测同一批数据两次运行分别给出 200/200 和
# 95/200，方差很大，而 links 为空时 13 个簇的 article_count 会全是 0。
SIGNAL_CLUSTER_MIN_LINK_COVERAGE = min(
    1.0, max(0.0, float(os.getenv("SIGNAL_CLUSTER_MIN_LINK_COVERAGE", "0.9")))
)
SIGNAL_CLUSTER_MAX_ATTEMPTS = max(1, int(os.getenv("SIGNAL_CLUSTER_MAX_ATTEMPTS", "2")))


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
            # hidden_signal 与 reason 是 enrich 产出里分析密度最高的两个字段
            # （实测平均 131 / 50 字符）。加进索引只多约 14K tokens（占 200K 窗口
            # 的 7%），但能让模型基于实质内容归并，而不是靠标题猜。
            # 曾经省掉它们，结果模型自述「仅依赖索引分组，未通读明细文件」，
            # 对索引稀疏的文章只能「按标题/已知归属归入相应簇」。
            "signal": str(article.get("hidden_signal") or "")[:220],
            "why": str(article.get("reason") or "")[:120],
            "entities": [str(x)[:40] for x in (article.get("entities") or [])][:6],
            "keywords": [str(x)[:30] for x in (article.get("watch_keywords") or [])][:6],
            "imp": article.get("importance_score"),
            "sig": article.get("signal_type"),
            "date": str(article.get("publish_time") or "")[:10],
        })
        detail: dict[str, Any] = {"ref": ref, "id": real_id}
        for key in ("title", "description", "cluster_hint", "entities", "watch_keywords",
                    "hidden_signal", "reason", "actionable", "prediction",
                    "disconfirming_evidence", "signal_type", "evidence_type",
                    "evidence_strength", "novelty_score", "impact_horizon", "market_stage",
                    "confidence", "importance_score", "publish_time", "source_feed_name", "url"):
            if key in article:
                detail[key] = article[key]
        detail_rows.append(detail)
    return index_rows, ref_to_id, detail_rows


def _build_prompt(
    *,
    articles: list[dict[str, Any]],
    index_rows: list[dict[str, Any]],
    detail_path: str,
    existing_clusters: list[dict[str, Any]],
    now_dt: datetime,
    retry_hint: str = "",
) -> str:
    """构造 prompt。

    设计取向是**质量优先**：索引里带 hidden_signal 与 reason（enrich 产出中分析
    密度最高的字段），让模型有实质内容可推理；明细文件保留其余字段供按需深入。

    曾经写过「主要依据索引」「最多 5 次 Grep」「不要 Read 整个文件」这类劝退话，
    结果模型一次文件都没打开，自述「仅依赖索引进行分组，未通读明细文件」，
    对索引稀疏的文章「按标题/已知归属归入相应簇」。轮数是省下来了，深度没了。
    现在改为说明何时值得深入，并把轮数上限交给 SIGNAL_CLUSTER_MAX_TURNS 控制。
    """
    return (
        f"共有 {len(articles)} 篇候选文章，当前时间 {now_dt.isoformat()}。\n\n"
        f"【索引】下面是**全部 {len(articles)} 篇**的索引，字段为 "
        "ref / 标题 / 聚类提示 / 隐藏信号 / 判定理由 / 实体 / 关键词 / 重要度 / 信号类型 / 日期：\n"
        f"{json.dumps(index_rows, ensure_ascii=False)}\n\n"
        f"【明细文件】每篇的完整字段（含 description、actionable、prediction、"
        f"disconfirming_evidence、url、来源等）在 {detail_path}\n"
        '（JSONL，每行一篇，行内含 "ref" 字段）。用 Grep 按 ref 取单篇，例如：\n'
        f'    Grep  pattern=\'"ref": "a017"\'  path={detail_path}\n'
        "索引已足够完成大部分归并；**但当某几篇的归属拿不准、或需要判断它们是否真的"
        "属于同一长期信号时，应当去查明细再定**，不要凭标题猜。\n"
        "可以一次 Grep 多个 ref，也可以 Read 文件的某个区间来批量查看。\n\n"
        "【已有簇】\n"
        f"{json.dumps(existing_clusters, ensure_ascii=False)}\n\n"
        "【输出要求】\n"
        "1. 将相同或高度相关的**长期信号**归并为同一 cluster；"
        "与 AI/智能体无关的噪声单独成簇，不要硬塞进主题簇。\n"
        "2. 不需要输出 links —— 归属关系由程序根据簇的 entities 和 keywords 自动分配。"
        "   请确保每个簇的 entities 和 keywords 足够具体，程序靠它们把文章归入簇。\n"
        "3. 不要输出规则解释，只输出结构化 JSON。\n"
        "4. 不要输出 recent_count_7d、previous_count_7d、burst_ratio、source_count、article_count。"
        + (f"\n\n【上一次的问题，本次必须修正】{retry_hint}" if retry_hint else "")
    )


def _assign_links_by_similarity(
    articles: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    ref_to_id: dict[str, str],
) -> list[dict[str, Any]]:
    """根据簇的 entities / keywords / label 把文章归入最匹配的簇。

    比对策略：每篇文章与每个簇做 token 交集，交最多的即归属；
    全零则用 normalized_label 的序列相似度；仍无则归入噪声簇。
    """
    import difflib

    def _tokens(*parts: Any) -> set[str]:
        out: set[str] = set()
        for part in parts:
            if isinstance(part, str):
                out.update(part.lower().replace("-", "_").split("_"))
            elif isinstance(part, (list, tuple)):
                for item in part:
                    if isinstance(item, str):
                        out.update(item.lower().replace("-", "_").split("_"))
        return {t for t in out if len(t) >= 2}

    noise_idx = [i for i, c in enumerate(clusters)
                 if any(k in str(c.get("label", "")) + str(c.get("normalized_label", ""))
                       for k in ("噪声", "无关", "noise", "other", "非 AI"))]

    cluster_tokens = [
        _tokens(c.get("entities"), c.get("watch_keywords"),
                c.get("normalized_label"), c.get("label"))
        for c in clusters
    ]

    links: list[dict[str, Any]] = []
    for i, article in enumerate(articles):
        art_tokens = _tokens(
            article.get("entities"), article.get("watch_keywords"),
            article.get("cluster_hint"), article.get("title"),
        )
        best_idx, best_score = -1, 0
        for ci, ct in enumerate(cluster_tokens):
            overlap = len(art_tokens & ct)
            if overlap > best_score:
                best_score, best_idx = overlap, ci
        if best_idx < 0 and art_tokens and clusters:
            hint = str(article.get("cluster_hint") or article.get("title") or "")
            best_ratio = 0.0
            for ci, cluster in enumerate(clusters):
                label = str(cluster.get("normalized_label") or cluster.get("label") or "")
                if not label:
                    continue
                ratio = difflib.SequenceMatcher(None, hint.lower(), label.lower()).ratio()
                if ratio > best_ratio:
                    best_ratio, best_idx = ratio, ci
        if best_idx < 0 and noise_idx:
            best_idx = noise_idx[0]
        if best_idx >= 0:
            ref = f"a{i + 1:03d}"
            real_id = ref_to_id.get(ref, str(article.get("id") or ""))
            cluster_key = str(clusters[best_idx].get("cluster_key") or "")
            if real_id and cluster_key:
                links.append({
                    "cluster_key": cluster_key,
                    "article_id": real_id,
                    "relevance_score": round(min(1.0, best_score / 5) if best_score > 0 else 0.5, 2),
                })
    return links


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

    real_ids = {str(a["id"]) for a in articles if a.get("id")}
    result: dict[str, Any] = {"clusters": [], "links": [], "unmapped_refs": 0}
    best: dict[str, Any] = result
    best_coverage = -1.0

    try:
        retry_hint = ""
        for attempt in range(1, SIGNAL_CLUSTER_MAX_ATTEMPTS + 1):
            prompt = _build_prompt(
                articles=articles,
                index_rows=index_rows,
                detail_path=detail_path,
                existing_clusters=existing_clusters or [],
                now_dt=now_dt,
                retry_hint=retry_hint,
            )
            sdk_logger = make_sdk_logger("signal_cluster", log_event=log_event,
                                        article_count=len(articles),
                                        existing_cluster_count=len(existing_clusters or []),
                                        prompt_chars=len(prompt),
                                        detail_path=detail_path,
                                        attempt=attempt)

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
                        timeout_seconds=_agent_timeout("SIGNAL_CLUSTER_AGENT_TIMEOUT_SECONDS", default=1800, minimum=120),
                        setting_sources=None,
                        sdk_log=sdk_logger,
                    ),
                    agent_name="signal_cluster",
                    validate=lambda d: isinstance(d.get("clusters"), list),
                    sdk_log=log_event,
                )
            )
            result = _validate_payload(payload, real_ids, ref_to_id=ref_to_id)

            # 模型不再被要求输出 links：200 条 × 3 字段的结构化输出是
            # error_max_structured_output_retries 的根因。Python 侧根据簇的
            # entities/keywords 自动分配，覆盖率恒为 100%，无结构化失败风险。
            if not result["links"] and result["clusters"] and articles:
                result["links"] = _assign_links_by_similarity(
                    articles, result["clusters"], ref_to_id
                )
            coverage = (len(result["links"]) / len(articles)) if articles else 1.0

            # 保留覆盖率最高的一次：重试是为了提高质量，不能因为重试更差而丢掉好结果
            if coverage > best_coverage:
                best, best_coverage = result, coverage

            # links 覆盖率必须显式告警。曾有一次运行 links 返回空数组，13 个簇全部
            # article_count=0、signal_cluster_articles 空表，但整条链路零告警，
            # 是查数据库时才发现的 —— "成功"的事件路径掩盖了空结果。
            if log_event:
                log_event(
                    "INFO" if coverage >= SIGNAL_CLUSTER_MIN_LINK_COVERAGE else "WARN",
                    "signal_cluster_link_coverage",
                    stage="cluster",
                    attempt=attempt,
                    articles=len(articles),
                    links=len(result["links"]),
                    clusters=len(result["clusters"]),
                    coverage=round(coverage, 3),
                    min_coverage=SIGNAL_CLUSTER_MIN_LINK_COVERAGE,
                    unmapped=result.get("unmapped_refs", 0),
                )

            if coverage >= SIGNAL_CLUSTER_MIN_LINK_COVERAGE:
                break
            if attempt >= SIGNAL_CLUSTER_MAX_ATTEMPTS:
                break
            # 实测同一批数据两次运行分别给出 200/200 和 95/200，方差很大，
            # 所以覆盖率不足时带着明确的缺口数字重试一次。
            retry_hint = (
                f"上一次只输出了 {len(result['links'])}/{len(articles)} 条 links，"
                f"覆盖率 {coverage:.0%}，低于要求的 {SIGNAL_CLUSTER_MIN_LINK_COVERAGE:.0%}。"
                f"请确保 clusters 数组中的 entities 和 keywords 足够具体，"
                f"程序靠它们把文章归入簇，太泛会导致归属错误。"
            )
            if log_event:
                log_event("WARN", "signal_cluster_low_coverage_retry", stage="cluster",
                          attempt=attempt, coverage=round(coverage, 3),
                          next_attempt=attempt + 1)
    finally:
        cleanup_temp_files(detail_path)

    return best


def _validate_payload(
    payload: dict[str, Any],
    article_ids: set[str],
    *,
    ref_to_id: dict[str, str] | None = None,
) -> dict[str, Any]:
    clusters = payload.get("clusters")
    # links 已从模型输出中移除（Python 自动分配），但兼容旧模型仍输出 links 的情况
    links = payload.get("links")
    if links is None:
        links = []
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
