from rss2cubox import export_web


def test_build_updates_sorted_and_scored() -> None:
    state = {
        'sent': {
            'a': {'url': 'https://example.com/a', 'ts': '2026-01-01T00:00:00+00:00'},
            'b': {'url': 'https://example.com/b', 'ts': '2026-01-02T00:00:00+00:00'},
        },
        'ai': {
            'b': {'score': 0.9, 'tags': ['ai']},
        },
    }
    out = export_web.build_updates(state, limit=10)
    assert [row['id'] for row in out] == ['b', 'a']
    assert out[0]['score'] == 0.9
    assert out[0]['source'] == 'example.com'


def test_merge_history_rows_dedup_and_limit() -> None:
    history = [
        {
            'id': 'x',
            'time': '2026-01-01T00:00:00+00:00',
            'source_feed': 'https://feed.example/rss',
            'url': 'https://example.com/x',
            'title': 'x',
            'status': 'pushed',
            'run_id': '1',
        }
    ]
    run_rows = [
        {
            'id': 'x',
            'time': '2026-01-01T00:00:00+00:00',
            'source_feed': 'https://feed.example/rss',
            'url': 'https://example.com/x',
            'title': 'x',
            'status': 'pushed',
            'run_id': '1',
        },
        {
            'id': 'y',
            'time': '2026-01-02T00:00:00+00:00',
            'source_feed': '/sspai/index',
            'url': 'https://example.com/y',
            'title': 'y',
            'status': 'dropped',
            'drop_reason': 'ai_keep_false',
            'run_id': '2',
        },
    ]
    merged = export_web.merge_history_rows(history, run_rows, history_limit=10)
    assert len(merged) == 2
    assert merged[0]['id'] == 'y'
    assert merged[0]['source'] == '/sspai/index'


def test_export_web_data_with_run_events(tmp_path) -> None:
    state_file = tmp_path / 'state.json'
    run_events_file = tmp_path / 'run_events.jsonl'
    history_file = tmp_path / 'updates_history.jsonl'
    updates_file = tmp_path / 'updates.json'
    metrics_file = tmp_path / 'metrics.json'

    state_file.write_text('{"sent":{},"ai":{}}', encoding='utf-8')
    run_events_file.write_text(
        '\n'.join(
            [
                '{"id":"a","time":"2026-01-02T00:00:00+00:00","source_feed":"https://feed.example/rss","url":"https://example.com/a","title":"A","status":"pushed","pushed":true,"score":0.9,"run_id":"100"}',
                '{"id":"b","time":"2026-01-01T00:00:00+00:00","source_feed":"https://feed.example/rss","url":"https://example.com/b","title":"B","status":"dropped","drop_reason":"ai_keep_false","score":0.2,"run_id":"100"}',
            ]
        )
        + '\n',
        encoding='utf-8',
    )

    updates_count, sources = export_web.export_web_data(
        state_file=state_file,
        run_events_file=run_events_file,
        history_file=history_file,
        updates_file=updates_file,
        metrics_file=metrics_file,
        limit=10,
        history_limit=100,
    )

    assert updates_count == 2
    assert sources == 1
    assert history_file.exists()
    metrics = metrics_file.read_text(encoding='utf-8')
    assert '"pushed_total": 1' in metrics
    assert '"dropped_total": 1' in metrics


def test_build_metrics() -> None:
    updates = [
        {'source': 'a.com', 'status': 'pushed'},
        {'source': 'a.com', 'status': 'dropped', 'drop_reason': 'x'},
        {'source': 'b.com', 'status': 'failed', 'drop_reason': 'y'},
    ]
    m = export_web.build_metrics(updates)
    assert m['updates_total'] == 3
    assert m['sources_total'] == 2
    assert m['pushed_total'] == 1
    assert m['dropped_total'] == 1
    assert m['failed_total'] == 1
    assert m['top_sources'][0]['source'] == 'a.com'
    assert m['top_sources'][0]['count'] == 2
