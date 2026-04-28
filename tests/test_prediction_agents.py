from datetime import datetime, timezone

import pytest

from rss2cubox import prediction_agent, prediction_review_agent, signal_cluster_agent
from rss2cubox.prediction_agent import run_trend_prediction_agent
from rss2cubox.prediction_review_agent import run_prediction_review_agent
from rss2cubox.signal_cluster_agent import build_cluster_key, run_signal_cluster_agent


NOW = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)


def _walk_schema_nodes(value):  # noqa: ANN001
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_schema_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_schema_nodes(child)


def test_prediction_agent_schemas_use_single_json_types() -> None:
    schemas = [
        signal_cluster_agent.SIGNAL_CLUSTER_OUTPUT_SCHEMA,
        prediction_agent.TREND_PREDICTION_OUTPUT_SCHEMA,
        prediction_review_agent.PREDICTION_REVIEW_OUTPUT_SCHEMA,
    ]

    for schema in schemas:
        for node in _walk_schema_nodes(schema):
            if "type" in node:
                assert isinstance(node["type"], str)


def test_signal_cluster_agent_groups_articles_by_signal_type_and_cluster_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    articles = [
        {
            "id": "a1",
            "title": "Codex enters CI",
            "source_feed_name": "OpenAI",
            "publish_time": "2026-04-27T10:00:00+00:00",
            "signal_type": 3,
            "importance_score": 4,
            "evidence_strength": 4,
            "novelty_score": 4,
            "confidence": 4,
            "cluster_hint": "异步软件工程代理",
            "entities": ["OpenAI", "Codex"],
            "watch_keywords": ["coding agent", "CI agent"],
        },
        {
            "id": "a2",
            "title": "Coding agent PR automation",
            "source_feed_name": "Hacker News",
            "publish_time": "2026-04-26T10:00:00+00:00",
            "signal_type": 3,
            "importance_score": 3,
            "evidence_strength": 3,
            "novelty_score": 3,
            "confidence": 4,
            "cluster_hint": "异步软件工程代理",
            "entities": ["GitHub"],
            "watch_keywords": ["PR automation"],
        },
    ]

    async def fake_run_json_agent(**kwargs):  # noqa: ANN001
        assert "Signal Cluster Agent" in kwargs["system_prompt"]
        return {
            "clusters": [{
                "cluster_key": "3:异步软件工程代理",
                "label": "异步软件工程代理",
                "normalized_label": "异步软件工程代理",
                "signal_type": 3,
                "status": "warming",
                "summary": "AI coding agent 正进入真实工程流程。",
                "entities": ["OpenAI", "Codex", "GitHub"],
                "watch_keywords": ["coding agent", "CI agent", "PR automation"],
                "first_seen_at": "2026-04-26T10:00:00+00:00",
                "last_seen_at": "2026-04-27T10:00:00+00:00",
                "article_count": 2,
                "source_count": 2,
                "avg_importance": 3.5,
                "avg_evidence_strength": 3.5,
                "avg_novelty": 3.5,
                "avg_confidence": 4,
                "recent_count_7d": 2,
                "previous_count_7d": 0,
                "burst_ratio": 4,
            }],
            "links": [
                {"cluster_key": "3:异步软件工程代理", "article_id": "a1", "relevance_score": 1},
                {"cluster_key": "3:异步软件工程代理", "article_id": "a2", "relevance_score": 1},
            ],
        }

    monkeypatch.setattr(signal_cluster_agent, "run_json_agent", fake_run_json_agent)

    result = run_signal_cluster_agent(articles, now=NOW)

    assert len(result["clusters"]) == 1
    cluster = result["clusters"][0]
    assert cluster["cluster_key"] == "3:异步软件工程代理"
    assert cluster["label"] == "异步软件工程代理"
    assert cluster["article_count"] == 2
    assert cluster["source_count"] == 2
    assert cluster["status"] in {"new", "warming", "bursting"}
    assert {link["article_id"] for link in result["links"]} == {"a1", "a2"}


def test_build_cluster_key_falls_back_to_title_when_hint_missing() -> None:
    key = build_cluster_key({"signal_type": 12, "title": "A new AI workflow"})
    assert key == "12:a-new-ai-workflow"


def test_trend_prediction_agent_creates_verifiable_prediction_from_active_cluster(monkeypatch: pytest.MonkeyPatch) -> None:
    clusters = [
        {
            "cluster_key": "3:异步软件工程代理",
            "label": "异步软件工程代理",
            "signal_type": 3,
            "status": "warming",
            "article_count": 5,
            "source_count": 3,
            "avg_evidence_strength": 4,
            "avg_novelty": 4,
            "avg_confidence": 4,
            "burst_ratio": 2.5,
            "watch_keywords": ["coding agent", "CI agent"],
            "summary": "AI coding agent 正进入真实工程流程。",
        }
    ]

    async def fake_run_json_agent(**kwargs):  # noqa: ANN001
        assert "Trend Prediction Agent" in kwargs["system_prompt"]
        return {
            "predictions": [{
                "signal_cluster_key": "3:异步软件工程代理",
                "prediction_type": 1,
                "created_at": "2026-04-28T12:00:00+00:00",
                "target_start_at": "2026-04-28T12:00:00+00:00",
                "target_end_at": "2026-05-05T12:00:00+00:00",
                "horizon_days": 7,
                "prediction_title": "异步软件工程代理未来7天验证",
                "prediction_body": "未来7天该方向应出现多源工程实践证据。",
                "watch_keywords": ["coding agent", "CI agent"],
                "expected_evidence": {
                    "minimum_support_count": 2,
                    "required_source_count": 2,
                    "required_evidence_types": [1, 4, 5, 9],
                },
                "disconfirming_evidence": "如果没有工程实践证据则降级。",
                "baseline_metrics": {"burst_ratio": 2.5},
                "confidence": 4,
                "status": "pending",
            }]
        }

    monkeypatch.setattr(prediction_agent, "run_json_agent", fake_run_json_agent)

    predictions = run_trend_prediction_agent(clusters, now=NOW)

    assert len(predictions) == 1
    prediction = predictions[0]
    assert prediction["signal_cluster_key"] == "3:异步软件工程代理"
    assert prediction["prediction_type"] == 1
    assert prediction["target_start_at"] == "2026-04-28T12:00:00+00:00"
    assert prediction["target_end_at"] == "2026-05-05T12:00:00+00:00"
    assert prediction["expected_evidence"]["minimum_support_count"] >= 2
    assert prediction["watch_keywords"] == ["coding agent", "CI agent"]


def test_prediction_review_agent_scores_supporting_articles(monkeypatch: pytest.MonkeyPatch) -> None:
    prediction = {
        "id": 1,
        "signal_cluster_key": "3:异步软件工程代理",
        "watch_keywords": ["coding agent", "CI agent"],
        "expected_evidence": {
            "minimum_support_count": 2,
            "required_source_count": 2,
            "required_evidence_types": [1, 4, 5, 9],
        },
    }
    articles = [
        {
            "id": "a1",
            "title": "Official coding agent CI launch",
            "hidden_signal": "coding agent enters CI",
            "source_feed_name": "OpenAI",
            "evidence_type": 1,
            "evidence_strength": 4,
        },
        {
            "id": "a2",
            "title": "PR automation with CI agent",
            "hidden_signal": "PR automation workflow",
            "source_feed_name": "GitHub",
            "evidence_type": 9,
            "evidence_strength": 4,
        },
    ]

    async def fake_run_json_agent(**kwargs):  # noqa: ANN001
        assert "Prediction Review Agent" in kwargs["system_prompt"]
        return {
            "prediction_id": 1,
            "score": 4,
            "hit_level": "strong",
            "supporting_articles": ["a1", "a2"],
            "contradicting_articles": [],
            "actual_observation": "目标窗口出现多源工程实践证据。",
            "why_score": "满足支持数量和来源要求。",
            "improvement_advice": "下次提高官方或开源证据要求。",
            "review_metrics": {
                "support_count": 2,
                "source_count": 2,
                "avg_evidence_strength": 4,
                "contradiction_count": 0,
            },
        }

    monkeypatch.setattr(prediction_review_agent, "run_json_agent", fake_run_json_agent)

    review = run_prediction_review_agent(prediction, articles)

    assert review["prediction_id"] == 1
    assert review["score"] >= 4
    assert review["hit_level"] in {"strong", "exact"}
    assert review["supporting_articles"] == ["a1", "a2"]
    assert review["review_metrics"]["support_count"] == 2
    assert review["review_metrics"]["source_count"] == 2
