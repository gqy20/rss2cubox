"""Rule-based Prediction Review Agent."""
from __future__ import annotations

from typing import Any


def run_prediction_review_agent(prediction: dict[str, Any], articles: list[dict[str, Any]]) -> dict[str, Any]:
    expected = prediction.get("expected_evidence") if isinstance(prediction.get("expected_evidence"), dict) else {}
    minimum_support = int(expected.get("minimum_support_count") or 2)
    required_source_count = int(expected.get("required_source_count") or 2)
    required_types = set(expected.get("required_evidence_types") or [])
    keywords = [str(value).lower() for value in prediction.get("watch_keywords", []) if str(value).strip()]

    supporting: list[dict[str, Any]] = []
    contradicting: list[dict[str, Any]] = []
    for article in articles:
        if _matches(article, keywords):
            supporting.append(article)
        elif _looks_contradicting(article, keywords):
            contradicting.append(article)

    source_names = {str(item.get("source_feed_name") or item.get("source") or "").strip() for item in supporting}
    source_names.discard("")
    evidence_values = [item.get("evidence_strength") for item in supporting if isinstance(item.get("evidence_strength"), (int, float))]
    avg_evidence = round(sum(evidence_values) / len(evidence_values), 2) if evidence_values else 0
    required_type_hits = sum(1 for item in supporting if item.get("evidence_type") in required_types)

    support_count = len(supporting)
    source_count = len(source_names)
    score = _score(
        support_count=support_count,
        minimum_support=minimum_support,
        source_count=source_count,
        required_source_count=required_source_count,
        avg_evidence=avg_evidence,
        required_type_hits=required_type_hits,
        contradiction_count=len(contradicting),
    )
    hit_level = _hit_level(score)

    return {
        "prediction_id": prediction.get("id"),
        "score": score,
        "hit_level": hit_level,
        "supporting_articles": [item["id"] for item in supporting if item.get("id")],
        "contradicting_articles": [item["id"] for item in contradicting if item.get("id")],
        "actual_observation": _observation(support_count, source_count, avg_evidence),
        "why_score": _why_score(score, support_count, minimum_support, source_count, required_source_count),
        "improvement_advice": _improvement(score),
        "review_metrics": {
            "keyword_hits": support_count,
            "support_count": support_count,
            "source_count": source_count,
            "avg_evidence_strength": avg_evidence,
            "required_type_hits": required_type_hits,
            "contradiction_count": len(contradicting),
        },
    }


def _matches(article: dict[str, Any], keywords: list[str]) -> bool:
    if not keywords:
        return True
    text = " ".join(
        str(article.get(key) or "")
        for key in ("title", "description", "hidden_signal", "reason", "actionable", "cluster_hint")
    ).lower()
    return any(keyword in text for keyword in keywords)


def _looks_contradicting(article: dict[str, Any], keywords: list[str]) -> bool:
    if not _matches(article, keywords):
        return False
    text = " ".join(str(article.get(key) or "") for key in ("title", "hidden_signal", "reason")).lower()
    return any(token in text for token in ("fails", "failed", "decline", "降温", "失败", "证伪", "放弃"))


def _score(
    *,
    support_count: int,
    minimum_support: int,
    source_count: int,
    required_source_count: int,
    avg_evidence: float,
    required_type_hits: int,
    contradiction_count: int,
) -> int:
    if contradiction_count > support_count:
        return 1
    if support_count <= 0:
        return 1
    if support_count < minimum_support:
        return 2
    if source_count < required_source_count:
        return 3
    if avg_evidence >= 4 and required_type_hits >= minimum_support:
        return 5
    if avg_evidence >= 3:
        return 4
    return 3


def _hit_level(score: int) -> str:
    return {
        1: "miss",
        2: "weak",
        3: "partial",
        4: "strong",
        5: "exact",
    }[score]


def _observation(support_count: int, source_count: int, avg_evidence: float) -> str:
    return f"目标窗口内找到 {support_count} 条支持证据，覆盖 {source_count} 个来源，平均证据强度 {avg_evidence}。"


def _why_score(score: int, support_count: int, minimum_support: int, source_count: int, required_source_count: int) -> str:
    if score <= 2:
        return f"支持证据不足，找到 {support_count} 条，低于要求 {minimum_support} 条。"
    if score == 3:
        return f"方向有证据，但来源覆盖不足，找到 {source_count} 个来源，要求 {required_source_count} 个。"
    return "预测方向获得多源证据支持，证据质量满足主要验证条件。"


def _improvement(score: int) -> str:
    if score >= 4:
        return "下次可提高验证条件，要求更硬的官方、代码或产品证据。"
    return "下次应收紧关键词和证据类型，避免把讨论热度误判为实质进展。"
