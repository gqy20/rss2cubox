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


def test_build_metrics() -> None:
    updates = [
        {'source': 'a.com'},
        {'source': 'a.com'},
        {'source': 'b.com'},
    ]
    m = export_web.build_metrics(updates)
    assert m['updates_total'] == 3
    assert m['sources_total'] == 2
    assert m['top_sources'][0]['source'] == 'a.com'
    assert m['top_sources'][0]['count'] == 2
