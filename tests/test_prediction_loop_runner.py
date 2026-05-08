from rss2cubox import prediction_loop_runner


def test_prediction_loop_runner_runs_all_agents_in_one_pass(monkeypatch):
    monkeypatch.setattr(prediction_loop_runner, "PREDICTION_LOOP_ENABLED", True)
    monkeypatch.setattr(prediction_loop_runner, "ensure_prediction_loop_schema", lambda: True)
    monkeypatch.setattr(prediction_loop_runner, "_stage_due", lambda stage, interval_hours: True)
    monkeypatch.setattr(prediction_loop_runner, "_mark_stage_done", lambda stage: None)
    monkeypatch.setattr(prediction_loop_runner, "get_recent_enriched_articles", lambda **kwargs: [{"id": "a1"}])
    monkeypatch.setattr(prediction_loop_runner, "get_existing_signal_clusters", lambda **kwargs: [{"cluster_key": "3:test"}])
    monkeypatch.setattr(prediction_loop_runner, "run_signal_cluster_agent", lambda articles, **kwargs: {
        "clusters": [{"cluster_key": "3:test"}],
        "links": [{"cluster_key": "3:test", "article_id": "a1"}],
    })
    monkeypatch.setattr(prediction_loop_runner, "save_signal_clusters", lambda result: {"3:test": 1})
    monkeypatch.setattr(prediction_loop_runner, "get_due_trend_predictions", lambda **kwargs: [{"id": 2, "signal_cluster_id": 1}])
    monkeypatch.setattr(prediction_loop_runner, "get_prediction_window_articles", lambda prediction, **kwargs: [{"id": "a1"}])
    monkeypatch.setattr(prediction_loop_runner, "run_prediction_review_agent", lambda prediction, articles, **kwargs: {"prediction_id": 2})
    monkeypatch.setattr(prediction_loop_runner, "save_prediction_review", lambda review: True)
    monkeypatch.setattr(prediction_loop_runner, "get_signal_clusters_for_prediction", lambda **kwargs: [{"id": 1, "cluster_key": "3:test"}])
    monkeypatch.setattr(prediction_loop_runner, "get_recent_prediction_reviews", lambda **kwargs: [{"score": 4}])
    monkeypatch.setattr(prediction_loop_runner, "run_trend_prediction_agent", lambda clusters, **kwargs: [{"signal_cluster_key": "3:test"}])
    monkeypatch.setattr(prediction_loop_runner, "save_trend_predictions", lambda predictions, cluster_ids: len(predictions))

    events = []
    monkeypatch.setattr(prediction_loop_runner, "log_event", lambda level, event, **fields: events.append((level, event, fields)))

    prediction_loop_runner.main()

    complete = [item for item in events if item[1] == "prediction_loop_complete"][0]
    assert complete[2]["articles"] == 1
    assert complete[2]["clusters"] == 1
    assert complete[2]["links"] == 1
    assert complete[2]["reviews"] == 1
    assert complete[2]["predictions"] == 1


def test_prediction_loop_runner_skips_stages_that_are_not_due(monkeypatch):
    monkeypatch.setattr(prediction_loop_runner, "PREDICTION_LOOP_ENABLED", True)
    monkeypatch.setattr(prediction_loop_runner, "ensure_prediction_loop_schema", lambda: True)
    monkeypatch.setattr(prediction_loop_runner, "_stage_due", lambda stage, interval_hours: False)

    called = {"cluster": False, "prediction": False, "review": False}
    monkeypatch.setattr(prediction_loop_runner, "get_recent_enriched_articles", lambda **kwargs: called.__setitem__("cluster", True))
    monkeypatch.setattr(prediction_loop_runner, "get_signal_clusters_for_prediction", lambda **kwargs: called.__setitem__("prediction", True))
    monkeypatch.setattr(prediction_loop_runner, "get_due_trend_predictions", lambda **kwargs: called.__setitem__("review", True))

    events = []
    monkeypatch.setattr(prediction_loop_runner, "log_event", lambda level, event, **fields: events.append((level, event, fields)))

    prediction_loop_runner.main()

    assert called == {"cluster": False, "prediction": False, "review": False}
    skipped = [item for item in events if item[1] == "prediction_stage_skipped"]
    assert {item[2]["stage"] for item in skipped} == {"cluster", "review", "generate", "daily_report"}
