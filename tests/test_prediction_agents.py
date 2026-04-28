from datetime import datetime, timezone

from rss2cubox.prediction_agent import run_trend_prediction_agent
from rss2cubox.prediction_review_agent import run_prediction_review_agent
from rss2cubox.signal_cluster_agent import build_cluster_key, run_signal_cluster_agent


NOW = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)


def test_signal_cluster_agent_groups_articles_by_signal_type_and_cluster_hint() -> None:
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


def test_trend_prediction_agent_creates_verifiable_prediction_from_active_cluster() -> None:
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

    predictions = run_trend_prediction_agent(clusters, now=NOW)

    assert len(predictions) == 1
    prediction = predictions[0]
    assert prediction["signal_cluster_key"] == "3:异步软件工程代理"
    assert prediction["prediction_type"] == 1
    assert prediction["target_start_at"] == "2026-04-28T12:00:00+00:00"
    assert prediction["target_end_at"] == "2026-05-05T12:00:00+00:00"
    assert prediction["expected_evidence"]["minimum_support_count"] >= 2
    assert prediction["watch_keywords"] == ["coding agent", "CI agent"]


def test_prediction_review_agent_scores_supporting_articles() -> None:
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

    review = run_prediction_review_agent(prediction, articles)

    assert review["prediction_id"] == 1
    assert review["score"] >= 4
    assert review["hit_level"] in {"strong", "exact"}
    assert review["supporting_articles"] == ["a1", "a2"]
    assert review["review_metrics"]["support_count"] == 2
    assert review["review_metrics"]["source_count"] == 2
