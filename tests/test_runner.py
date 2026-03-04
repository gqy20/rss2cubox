import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from rss2cubox import ai_pipeline
from rss2cubox import feed_sources, sync_pipeline
from rss2cubox import metrics
from rss2cubox import runner


def test_load_lines_ignores_blank_and_comment(tmp_path: Path) -> None:
    feeds = tmp_path / "feeds.txt"
    feeds.write_text("# comment\n\nhttps://a.example/rss\n  \nhttps://b.example/rss\n", encoding="utf-8")

    assert feed_sources.load_lines(feeds) == ["https://a.example/rss", "https://b.example/rss"]


def test_load_feed_specs_supports_sections(tmp_path: Path) -> None:
    feeds = tmp_path / "feeds.txt"
    feeds.write_text(
        "[rsshub]\n/sspai/index\n\n[direct]\nhttps://example.com/feed.xml\n",
        encoding="utf-8",
    )
    assert feed_sources.load_feed_specs(feeds) == [
        {"kind": "rsshub", "value": "/sspai/index"},
        {"kind": "direct", "value": "https://example.com/feed.xml"},
    ]


def test_resolve_feed_urls_with_rsshub_route() -> None:
    instances = ["https://a.rsshub.test", "https://b.rsshub.test"]
    pool = feed_sources.RSSHubInstancePool(instances=instances)
    assert feed_sources.resolve_feed_urls("rsshub", "/sspai/index", pool) == [
        "https://a.rsshub.test/sspai/index",
        "https://b.rsshub.test/sspai/index",
    ]
    assert feed_sources.resolve_feed_urls("rsshub", "rsshub://sspai/index", pool) == [
        "https://a.rsshub.test/sspai/index",
        "https://b.rsshub.test/sspai/index",
    ]


def test_parse_feed_with_fallback_uses_next_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    instances = ["https://bad.rsshub.test", "https://ok.rsshub.test"]
    pool = feed_sources.RSSHubInstancePool(instances=instances, cooldown_seconds=1)

    def fake_fetch(url: str):  # noqa: ANN001
        if url.startswith("https://bad.rsshub.test"):
            raise RuntimeError("boom")
        return SimpleNamespace(bozo=False, entries=[{"id": "1", "link": "https://example.com/1"}])

    selected, parsed, attempt = feed_sources.parse_feed_with_fallback(
        "rsshub",
        "/sspai/index",
        pool,
        fetcher=fake_fetch,
        log_event=lambda *_args, **_kwargs: None,
    )
    assert selected == "https://ok.rsshub.test/sspai/index"
    assert attempt == 2
    assert parsed is not None
    assert getattr(parsed, "bozo", True) is False


def test_load_rsshub_instances_from_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pool = tmp_path / "rsshub_instances.txt"
    pool.write_text("# comment\nhttps://x.rsshub.test/\nhttps://y.rsshub.test\n", encoding="utf-8")
    monkeypatch.delenv("RSSHUB_INSTANCES", raising=False)

    assert feed_sources.load_rsshub_instances(pool) == ["https://x.rsshub.test", "https://y.rsshub.test"]


def test_state_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_file = tmp_path / "state.json"
    _ = monkeypatch
    payload = {"sent": {"x": {"url": "https://example.com", "ts": "2026-01-01T00:00:00+00:00"}}}

    sync_pipeline.save_state(state_file, payload)
    assert sync_pipeline.load_state(state_file) == payload


def test_stable_id_prefers_entry_id() -> None:
    entry_a = {"id": "same", "link": "https://a", "title": "A"}
    entry_b = {"id": "same", "link": "https://b", "title": "B"}
    assert sync_pipeline.stable_id(entry_a) == sync_pipeline.stable_id(entry_b)


def test_passes_filter_include_exclude(monkeypatch: pytest.MonkeyPatch) -> None:
    _ = monkeypatch
    entry_ok = {"title": "OpenAI releases update"}
    entry_bad = {"title": "OpenAI hiring boom"}

    assert sync_pipeline.passes_filter(entry_ok, ["openai"], ["hiring"]) is True
    assert sync_pipeline.passes_filter(entry_bad, ["openai"], ["hiring"]) is False


def test_cubox_save_url_builds_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {}

    class Resp:
        text = "ok"

        @staticmethod
        def raise_for_status() -> None:
            return None

    def fake_post(url, json, timeout):  # noqa: ANN001
        calls["url"] = url
        calls["json"] = json
        calls["timeout"] = timeout
        return Resp()

    out = sync_pipeline.cubox_save_url(
        api_url="https://cubox.example/api",
        request_post=fake_post,
        url="https://example.com/post",
        title="t",
        description="d",
        tags=["news"],
        folder="Inbox",
    )

    assert out == "ok"
    assert calls["url"] == "https://cubox.example/api"
    assert calls["timeout"] == 30
    assert calls["json"] == {
        "type": "url",
        "content": "https://example.com/post",
        "title": "t",
        "description": "d",
        "tags": ["news"],
        "folder": "Inbox",
    }


def test_cubox_save_url_requires_api_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _ = monkeypatch
    with pytest.raises(RuntimeError):
        sync_pipeline.cubox_save_url(api_url=None, request_post=lambda *args, **kwargs: None, url="https://example.com")


def test_analyze_candidates_with_ai_prefers_tool_use(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {}

    class Resp:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict:
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "analyze_batch",
                        "input": {
                            "results": [
                                {
                                    "eid": "e1",
                                    "keep": True,
                                    "score": 0.92,
                                    "reason": "high signal",
                                    "tags": ["ai"],
                                    "brief": "good summary",
                                }
                            ]
                        },
                    }
                ]
            }

    def fake_post(url, headers, json, timeout):  # noqa: ANN001
        calls["url"] = url
        calls["headers"] = headers
        calls["json"] = json
        calls["timeout"] = timeout
        return Resp()

    monkeypatch.setattr(runner, "ANTHROPIC_AUTH_TOKEN", "token")
    monkeypatch.setattr(runner, "ANTHROPIC_MODEL", "model")
    monkeypatch.setattr(runner, "ANTHROPIC_BASE_URL", "https://api.example.com/anthropic")
    monkeypatch.setattr(runner, "AI_TIMEOUT_SECONDS", 12)
    monkeypatch.setattr(ai_pipeline.requests, "post", fake_post)

    out = ai_pipeline.analyze_candidates_with_ai(
        candidates=[{"eid": "e1", "url": "https://example.com/1", "title": "t", "description": "d"}],
        stage_metrics=runner.StageMetrics(),
        auth_token=runner.ANTHROPIC_AUTH_TOKEN,
        base_url=runner.ANTHROPIC_BASE_URL,
        model=runner.ANTHROPIC_MODEL,
        timeout_seconds=runner.AI_TIMEOUT_SECONDS,
        retry_attempts=runner.AI_RETRY_ATTEMPTS,
        retry_backoff_seconds=runner.AI_RETRY_BACKOFF_SECONDS,
        batch_size=runner.AI_BATCH_SIZE,
        log_event=lambda *_args, **_kwargs: None,
    )

    assert calls["url"] == "https://api.example.com/anthropic/v1/messages"
    assert calls["timeout"] == 12
    assert calls["json"]["tool_choice"] == {"type": "any"}
    assert calls["json"]["tools"][0]["name"] == "analyze_batch"
    assert out["e1"]["keep"] is True
    assert out["e1"]["score"] == 0.92
    assert out["e1"]["tags"] == ["ai"]


def test_analyze_candidates_with_ai_text_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resp:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            '{"results":[{"eid":"e2","keep":false,"score":0.3,'
                            '"reason":"low signal","tags":[],"brief":""}]}'
                        ),
                    }
                ]
            }

    monkeypatch.setattr(runner, "ANTHROPIC_AUTH_TOKEN", "token")
    monkeypatch.setattr(runner, "ANTHROPIC_MODEL", "model")
    monkeypatch.setattr(ai_pipeline.requests, "post", lambda *_, **__: Resp())

    out = ai_pipeline.analyze_candidates_with_ai(
        candidates=[{"eid": "e2", "url": "https://example.com/2", "title": "t2", "description": "d2"}],
        stage_metrics=runner.StageMetrics(),
        auth_token=runner.ANTHROPIC_AUTH_TOKEN,
        base_url=runner.ANTHROPIC_BASE_URL,
        model=runner.ANTHROPIC_MODEL,
        timeout_seconds=runner.AI_TIMEOUT_SECONDS,
        retry_attempts=runner.AI_RETRY_ATTEMPTS,
        retry_backoff_seconds=runner.AI_RETRY_BACKOFF_SECONDS,
        batch_size=runner.AI_BATCH_SIZE,
        log_event=lambda *_args, **_kwargs: None,
    )
    assert out["e2"]["keep"] is False
    assert out["e2"]["score"] == 0.3


def test_analyze_candidates_with_ai_retries_then_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resp:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict:
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "analyze_batch",
                        "input": {
                            "results": [
                                {
                                    "eid": "e3",
                                    "keep": True,
                                    "score": 0.88,
                                    "reason": "good",
                                    "tags": ["weekly"],
                                    "brief": "ok",
                                }
                            ]
                        },
                    }
                ]
            }

    calls = {"count": 0}

    def flaky_post(*_, **__):  # noqa: ANN001
        calls["count"] += 1
        if calls["count"] == 1:
            raise requests.exceptions.ReadTimeout("timeout")
        return Resp()

    monkeypatch.setattr(runner, "ANTHROPIC_AUTH_TOKEN", "token")
    monkeypatch.setattr(runner, "ANTHROPIC_MODEL", "model")
    monkeypatch.setattr(runner, "AI_RETRY_ATTEMPTS", 2)
    monkeypatch.setattr(runner, "AI_RETRY_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(ai_pipeline.requests, "post", flaky_post)
    monkeypatch.setattr(ai_pipeline.time, "sleep", lambda *_: None)

    out = ai_pipeline.analyze_candidates_with_ai(
        candidates=[{"eid": "e3", "url": "https://example.com/3", "title": "t3", "description": "d3"}],
        stage_metrics=runner.StageMetrics(),
        auth_token=runner.ANTHROPIC_AUTH_TOKEN,
        base_url=runner.ANTHROPIC_BASE_URL,
        model=runner.ANTHROPIC_MODEL,
        timeout_seconds=runner.AI_TIMEOUT_SECONDS,
        retry_attempts=runner.AI_RETRY_ATTEMPTS,
        retry_backoff_seconds=runner.AI_RETRY_BACKOFF_SECONDS,
        batch_size=runner.AI_BATCH_SIZE,
        log_event=lambda *_args, **_kwargs: None,
    )
    assert calls["count"] == 2
    assert out["e3"]["keep"] is True


def test_analyze_candidates_with_ai_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    batch_sizes = []

    class Resp:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        @staticmethod
        def raise_for_status() -> None:
            return None

        def json(self) -> dict:
            items = json.loads(self.payload["messages"][0]["content"])
            results = [
                {
                    "eid": item["eid"],
                    "keep": True,
                    "score": 0.9,
                    "reason": "ok",
                    "tags": ["ai"],
                    "brief": "brief",
                }
                for item in items
            ]
            return {
                "stop_reason": "tool_use",
                "content": [{"type": "tool_use", "name": "analyze_batch", "input": {"results": results}}],
            }

    def fake_post(url, headers, json, timeout):  # noqa: ANN001
        _ = (url, headers, timeout)
        items = json_loads(json["messages"][0]["content"])
        batch_sizes.append(len(items))
        return Resp(json)

    def json_loads(s: str) -> list[dict]:
        return json.loads(s)

    monkeypatch.setattr(runner, "ANTHROPIC_AUTH_TOKEN", "token")
    monkeypatch.setattr(runner, "ANTHROPIC_MODEL", "model")
    monkeypatch.setattr(runner, "AI_BATCH_SIZE", 3)
    monkeypatch.setattr(runner, "AI_RETRY_ATTEMPTS", 1)
    monkeypatch.setattr(ai_pipeline.requests, "post", fake_post)

    cands = [
        {"eid": f"e{i}", "url": f"https://example.com/{i}", "title": "t", "description": "d"}
        for i in range(7)
    ]
    out = ai_pipeline.analyze_candidates_with_ai(
        candidates=cands,
        stage_metrics=runner.StageMetrics(),
        auth_token=runner.ANTHROPIC_AUTH_TOKEN,
        base_url=runner.ANTHROPIC_BASE_URL,
        model=runner.ANTHROPIC_MODEL,
        timeout_seconds=runner.AI_TIMEOUT_SECONDS,
        retry_attempts=runner.AI_RETRY_ATTEMPTS,
        retry_backoff_seconds=runner.AI_RETRY_BACKOFF_SECONDS,
        batch_size=runner.AI_BATCH_SIZE,
        log_event=lambda *_args, **_kwargs: None,
    )
    assert batch_sizes == [3, 3, 1]
    assert len(out) == 7
    assert out["e0"]["keep"] is True


def test_main_dedup_and_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feeds_file = tmp_path / "feeds.txt"
    state_file = tmp_path / "state.json"
    feeds_file.write_text("https://feed.example/rss\n", encoding="utf-8")
    state_file.write_text('{"sent":{}}', encoding="utf-8")

    entries = [
        {"id": "1", "link": "https://example.com/1", "title": "First", "summary": "A"},
        {"id": "1", "link": "https://example.com/1", "title": "First duplicate", "summary": "A2"},
        {"id": "2", "link": "https://example.com/2", "title": "Second", "summary": "B"},
    ]

    pushed_urls = []

    def fake_fetch(url: str):  # noqa: ANN001
        assert url == "https://feed.example/rss"
        return SimpleNamespace(bozo=False, entries=entries)

    def fake_save(url: str, title: str, description: str, tags, folder: str):  # noqa: ANN001
        pushed_urls.append((url, title, description, tags, folder))
        return "ok"

    monkeypatch.setattr(runner, "FEEDS_FILE", feeds_file)
    monkeypatch.setattr(runner, "STATE_FILE", state_file)
    monkeypatch.setattr(runner, "RUN_EVENTS_FILE", tmp_path / "run_events.jsonl")
    monkeypatch.setattr(runner, "MAX_ITEMS_PER_RUN", 1)
    monkeypatch.setattr(runner, "KEYWORDS_INCLUDE", [])
    monkeypatch.setattr(runner, "KEYWORDS_EXCLUDE", [])
    monkeypatch.setattr(runner, "CUBOX_FOLDER", "RSS Inbox")
    monkeypatch.setattr(runner, "ANTHROPIC_AUTH_TOKEN", "")
    monkeypatch.setattr(runner, "ANTHROPIC_MODEL", "")
    monkeypatch.setattr(feed_sources, "fetch_and_parse_feed", lambda url, **_kwargs: fake_fetch(url))
    monkeypatch.setattr(runner.sync_pipeline, "cubox_save_url", lambda **kwargs: fake_save(
        kwargs["url"], kwargs.get("title", ""), kwargs.get("description", ""), kwargs.get("tags"), kwargs.get("folder", "")
    ))
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)

    runner.main()

    assert len(pushed_urls) == 1
    assert pushed_urls[0][0] == "https://example.com/1"
    state = sync_pipeline.load_state(state_file)
    assert len(state["sent"]) == 1


def test_main_feed_cursor_prefilter_and_state_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feeds_file = tmp_path / "feeds.txt"
    state_file = tmp_path / "state.json"
    feed_url = "https://feed.example/rss"
    feeds_file.write_text(f"{feed_url}\n", encoding="utf-8")
    state_file.write_text(
        json.dumps({"sent": {}, "feed_cursor": {feed_url: "2026-01-10T00:00:00+00:00"}}),
        encoding="utf-8",
    )

    entries = [
        {
            "id": "old",
            "link": "https://example.com/old",
            "title": "Old",
            "summary": "too old",
            "published": "2026-01-01T00:00:00+00:00",
        },
        {
            "id": "new",
            "link": "https://example.com/new",
            "title": "New",
            "summary": "fresh",
            "published": "2026-01-10T12:00:00+00:00",
        },
        {
            "id": "nodate",
            "link": "https://example.com/nodate",
            "title": "No Date",
            "summary": "no timestamp",
        },
    ]

    pushed_urls = []

    def fake_fetch(url: str):  # noqa: ANN001
        assert url == feed_url
        return SimpleNamespace(bozo=False, entries=entries)

    def fake_save(url: str, title: str, description: str, tags, folder: str):  # noqa: ANN001
        pushed_urls.append(url)
        return "ok"

    monkeypatch.setattr(runner, "FEEDS_FILE", feeds_file)
    monkeypatch.setattr(runner, "STATE_FILE", state_file)
    monkeypatch.setattr(runner, "RUN_EVENTS_FILE", tmp_path / "run_events.jsonl")
    monkeypatch.setattr(runner, "MAX_ITEMS_PER_RUN", 20)
    monkeypatch.setattr(runner, "KEYWORDS_INCLUDE", [])
    monkeypatch.setattr(runner, "KEYWORDS_EXCLUDE", [])
    monkeypatch.setattr(runner, "CUBOX_FOLDER", "RSS Inbox")
    monkeypatch.setattr(runner, "FEED_CURSOR_LOOKBACK_HOURS", 24)
    monkeypatch.setattr(runner, "ANTHROPIC_AUTH_TOKEN", "")
    monkeypatch.setattr(runner, "ANTHROPIC_MODEL", "")
    monkeypatch.setattr(feed_sources, "fetch_and_parse_feed", lambda url, **_kwargs: fake_fetch(url))
    monkeypatch.setattr(runner.sync_pipeline, "cubox_save_url", lambda **kwargs: fake_save(
        kwargs["url"], kwargs.get("title", ""), kwargs.get("description", ""), kwargs.get("tags"), kwargs.get("folder", "")
    ))
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)

    runner.main()

    assert "https://example.com/old" not in pushed_urls
    assert "https://example.com/new" in pushed_urls
    assert "https://example.com/nodate" in pushed_urls
    state = sync_pipeline.load_state(state_file)
    assert len(state["sent"]) == 2
    assert state["feed_cursor"][feed_url].startswith("2026-01-10T12:00:00")


def test_main_run_seen_dedup_across_feeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feeds_file = tmp_path / "feeds.txt"
    state_file = tmp_path / "state.json"
    feed_a = "https://feed-a.example/rss"
    feed_b = "https://feed-b.example/rss"
    feeds_file.write_text(f"{feed_a}\n{feed_b}\n", encoding="utf-8")
    state_file.write_text('{"sent":{}}', encoding="utf-8")

    shared_entry = {"id": "same-id", "link": "https://example.com/shared", "title": "Shared", "summary": "A"}
    entries_by_feed = {
        feed_a: [shared_entry],
        feed_b: [shared_entry],
    }
    pushed_urls = []

    def fake_fetch(url: str):  # noqa: ANN001
        return SimpleNamespace(bozo=False, entries=entries_by_feed[url])

    def fake_save(url: str, title: str, description: str, tags, folder: str):  # noqa: ANN001
        _ = (title, description, tags, folder)
        pushed_urls.append(url)
        return "ok"

    monkeypatch.setattr(runner, "FEEDS_FILE", feeds_file)
    monkeypatch.setattr(runner, "STATE_FILE", state_file)
    monkeypatch.setattr(runner, "RUN_EVENTS_FILE", tmp_path / "run_events.jsonl")
    monkeypatch.setattr(runner, "MAX_ITEMS_PER_RUN", 20)
    monkeypatch.setattr(runner, "KEYWORDS_INCLUDE", [])
    monkeypatch.setattr(runner, "KEYWORDS_EXCLUDE", [])
    monkeypatch.setattr(runner, "CUBOX_FOLDER", "RSS Inbox")
    monkeypatch.setattr(runner, "ANTHROPIC_AUTH_TOKEN", "")
    monkeypatch.setattr(runner, "ANTHROPIC_MODEL", "")
    monkeypatch.setattr(feed_sources, "fetch_and_parse_feed", lambda url, **_kwargs: fake_fetch(url))
    monkeypatch.setattr(runner.sync_pipeline, "cubox_save_url", lambda **kwargs: fake_save(
        kwargs["url"], kwargs.get("title", ""), kwargs.get("description", ""), kwargs.get("tags"), kwargs.get("folder", "")
    ))
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)

    runner.main()

    assert pushed_urls == ["https://example.com/shared"]
    state = sync_pipeline.load_state(state_file)
    assert len(state["sent"]) == 1


def test_reorder_candidates_by_ai_score() -> None:
    candidates = [
        {"eid": "a", "url": "https://example.com/a"},
        {"eid": "b", "url": "https://example.com/b"},
        {"eid": "c", "url": "https://example.com/c"},
    ]
    analyses = {
        "a": {"keep": True, "score": 0.65},
        "b": {"keep": True, "score": 0.95},
        "c": {"keep": False, "score": 0.99},
    }

    out = sync_pipeline.reorder_candidates_by_ai_score(
        candidates,
        analyses,
        ai_enabled=True,
        ai_min_score=0.6,
    )
    assert [item["eid"] for item in out] == ["b", "a", "c"]


def test_write_step_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary_file = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

    metrics.write_step_summary(
        {
            "feeds_total": 2,
            "feeds_invalid": 1,
            "fetched": 10,
            "deduped": 3,
            "missing_link": 1,
            "keyword_filtered": 2,
            "candidates": 4,
            "candidates_selected": 4,
            "ai_enabled": True,
            "ai_analyzed": 4,
            "ai_missing": 0,
            "ai_kept": 2,
            "ai_dropped_keep_false": 1,
            "ai_dropped_score": 1,
            "push_attempted": 2,
            "pushed": 2,
            "push_failed": 0,
            "state_size": 99,
        },
        str(summary_file),
    )

    content = summary_file.read_text(encoding="utf-8")
    assert "RSS2Cubox Run Summary" in content
    assert "| fetched | 10 |" in content
    assert "| ai_kept | 2 |" in content
    assert "| pushed | 2 |" in content


def test_feed_failure_backoff_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "FEED_FAILURE_COOLDOWN_SECONDS", 30)
    monkeypatch.setattr(runner, "FEED_FAILURE_COOLDOWN_MAX_SECONDS", 120)

    assert sync_pipeline.feed_failure_backoff_seconds(1, 30, 120) == 30
    assert sync_pipeline.feed_failure_backoff_seconds(2, 30, 120) == 60
    assert sync_pipeline.feed_failure_backoff_seconds(3, 30, 120) == 120
    assert sync_pipeline.feed_failure_backoff_seconds(4, 30, 120) == 120


def test_main_skips_feed_when_circuit_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feeds_file = tmp_path / "feeds.txt"
    state_file = tmp_path / "state.json"
    blocked_feed = "https://blocked.example/rss"
    ok_feed = "https://ok.example/rss"
    feeds_file.write_text(f"{blocked_feed}\n{ok_feed}\n", encoding="utf-8")
    cooldown_until = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    state_file.write_text(
        json.dumps({"sent": {}, "feed_failures": {blocked_feed: {"count": 2, "cooldown_until": cooldown_until}}}),
        encoding="utf-8",
    )

    fetched = []
    pushed_urls = []

    def fake_fetch(url: str):  # noqa: ANN001
        fetched.append(url)
        return SimpleNamespace(bozo=False, entries=[{"id": url, "link": f"{url}/1", "title": "t", "summary": "s"}])

    def fake_save(url: str, title: str, description: str, tags, folder: str):  # noqa: ANN001
        _ = (title, description, tags, folder)
        pushed_urls.append(url)
        return "ok"

    monkeypatch.setattr(runner, "FEEDS_FILE", feeds_file)
    monkeypatch.setattr(runner, "STATE_FILE", state_file)
    monkeypatch.setattr(runner, "RUN_EVENTS_FILE", tmp_path / "run_events.jsonl")
    monkeypatch.setattr(runner, "MAX_ITEMS_PER_RUN", 20)
    monkeypatch.setattr(runner, "KEYWORDS_INCLUDE", [])
    monkeypatch.setattr(runner, "KEYWORDS_EXCLUDE", [])
    monkeypatch.setattr(runner, "CUBOX_FOLDER", "RSS Inbox")
    monkeypatch.setattr(runner, "ANTHROPIC_AUTH_TOKEN", "")
    monkeypatch.setattr(runner, "ANTHROPIC_MODEL", "")
    monkeypatch.setattr(runner, "FEED_FETCH_CONCURRENCY", 4)
    monkeypatch.setattr(feed_sources, "fetch_and_parse_feed", lambda url, **_kwargs: fake_fetch(url))
    monkeypatch.setattr(runner.sync_pipeline, "cubox_save_url", lambda **kwargs: fake_save(
        kwargs["url"], kwargs.get("title", ""), kwargs.get("description", ""), kwargs.get("tags"), kwargs.get("folder", "")
    ))
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)

    runner.main()

    assert blocked_feed not in fetched
    assert ok_feed in fetched
    assert pushed_urls == [f"{ok_feed}/1"]
