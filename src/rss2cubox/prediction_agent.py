"""Rule-based Trend Prediction Agent."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def run_trend_prediction_agent(
    clusters: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    horizon_days: int = 7,
    max_predictions: int = 5,
) -> list[dict[str, Any]]:
    now_dt = now or datetime.now(timezone.utc)
    target_end = now_dt + timedelta(days=horizon_days)
    eligible = [cluster for cluster in clusters if _is_predictable(cluster)]
    eligible.sort(key=_rank_cluster, reverse=True)

    predictions: list[dict[str, Any]] = []
    for cluster in eligible[:max_predictions]:
        confidence = _confidence(cluster)
        minimum_support = 3 if confidence >= 4 else 2
        source_count = max(2, min(3, int(cluster.get("source_count") or 0)))
        prediction_type = _prediction_type(cluster)
        label = str(cluster.get("label") or cluster.get("cluster_key") or "未命名信号")

        predictions.append({
            "signal_cluster_key": cluster.get("cluster_key"),
            "prediction_type": prediction_type,
            "created_at": now_dt.isoformat(),
            "target_start_at": now_dt.isoformat(),
            "target_end_at": target_end.isoformat(),
            "horizon_days": horizon_days,
            "prediction_title": f"{label}未来{horizon_days}天验证",
            "prediction_body": _prediction_body(label, cluster, horizon_days, minimum_support, source_count),
            "watch_keywords": _watch_keywords(cluster),
            "expected_evidence": {
                "minimum_support_count": minimum_support,
                "required_source_count": source_count,
                "required_evidence_types": _required_evidence_types(cluster),
            },
            "disconfirming_evidence": f"如果未来{horizon_days}天没有多源实质证据，或仅停留在观点讨论，该信号降级。",
            "baseline_metrics": {
                "article_count": cluster.get("article_count", 0),
                "source_count": cluster.get("source_count", 0),
                "burst_ratio": cluster.get("burst_ratio", 0),
                "avg_evidence_strength": cluster.get("avg_evidence_strength"),
                "avg_novelty": cluster.get("avg_novelty"),
                "avg_confidence": cluster.get("avg_confidence"),
            },
            "confidence": confidence,
            "status": "pending",
        })

    return predictions


def _is_predictable(cluster: dict[str, Any]) -> bool:
    return (
        str(cluster.get("status") or "") in {"new", "warming", "bursting"}
        and int(cluster.get("article_count") or 0) >= 2
        and float(cluster.get("avg_confidence") or 0) >= 3
    )


def _rank_cluster(cluster: dict[str, Any]) -> tuple[float, float, float, int]:
    return (
        float(cluster.get("burst_ratio") or 0),
        float(cluster.get("avg_evidence_strength") or 0),
        float(cluster.get("avg_novelty") or 0),
        int(cluster.get("source_count") or 0),
    )


def _confidence(cluster: dict[str, Any]) -> int:
    avg_confidence = float(cluster.get("avg_confidence") or 3)
    evidence = float(cluster.get("avg_evidence_strength") or 3)
    source_count = int(cluster.get("source_count") or 1)
    score = round((avg_confidence + evidence) / 2)
    if source_count >= 3:
        score += 1
    return max(1, min(5, score))


def _prediction_type(cluster: dict[str, Any]) -> int:
    status = str(cluster.get("status") or "")
    if status in {"warming", "bursting"}:
        return 1
    if float(cluster.get("avg_evidence_strength") or 0) >= 4:
        return 2
    if int(cluster.get("source_count") or 0) >= 3:
        return 3
    return 1


def _required_evidence_types(cluster: dict[str, Any]) -> list[int]:
    signal_type = cluster.get("signal_type")
    if signal_type in {3, 4, 5}:
        return [1, 4, 5, 9]
    if signal_type == 6:
        return [2, 3, 4, 9]
    if signal_type == 9:
        return [1, 6, 7, 10]
    return [1, 2, 4, 5, 9]


def _watch_keywords(cluster: dict[str, Any]) -> list[str]:
    values = cluster.get("watch_keywords")
    if isinstance(values, list) and values:
        return [str(value).strip() for value in values if str(value).strip()][:8]
    label = str(cluster.get("label") or "").strip()
    return [label] if label else []


def _prediction_body(label: str, cluster: dict[str, Any], horizon_days: int, minimum_support: int, source_count: int) -> str:
    return (
        f"未来{horizon_days}天，{label}应继续出现可验证进展：至少出现{minimum_support}条支持证据，"
        f"覆盖不少于{source_count}个独立来源，并且包含官方、代码、产品或工程实践类证据。"
    )
