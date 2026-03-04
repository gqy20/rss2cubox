import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from rss2cubox import runner


def test_load_lines_ignores_blank_and_comment(tmp_path: Path) -> None:
    feeds = tmp_path / "feeds.txt"
    feeds.write_text("# comment\n\nhttps://a.example/rss\n  \nhttps://b.example/rss\n", encoding="utf-8")

    assert runner.load_lines(feeds) == ["https://a.example/rss", "https://b.example/rss"]


def test_load_feed_specs_supports_sections(tmp_path: Path) -> None:
    feeds = tmp_path / "feeds.txt"
    feeds.write_text(
        "[rsshub]\n/sspai/index\n\n[direct]\nhttps://example.com/feed.xml\n",
        encoding="utf-8",
    )
    assert runner.load_feed_specs(feeds) == [
        {"kind": "rsshub", "value": "/sspai/index"},
        {"kind": "direct", "value": "https://example.com/feed.xml"},
    ]


def test_resolve_feed_urls_with_rsshub_route() -> None:
    instances = ["https://a.rsshub.test", "https://b.rsshub.test"]
    assert runner.resolve_feed_urls("rsshub", "/sspai/index", instances) == [
        "https://a.rsshub.test/sspai/index",
        "https://b.rsshub.test/sspai/index",
    ]
    assert runner.resolve_feed_urls("rsshub", "rsshub://sspai/index", instances) == [
        "https://a.rsshub.test/sspai/index",
        "https://b.rsshub.test/sspai/index",
    ]


def test_parse_feed_with_fallback_uses_next_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    instances = ["https://bad.rsshub.test", "https://ok.rsshub.test"]

    def fake_parse(url: str):  # noqa: ANN001
        if url.startswith("https://bad.rsshub.test"):
            return SimpleNamespace(bozo=True, entries=[])
        return SimpleNamespace(bozo=False, entries=[{"id": "1", "link": "https://example.com/1"}])

    monkeypatch.setattr(runner.feedparser, "parse", fake_parse)

    selected, parsed, attempt = runner.parse_feed_with_fallback("rsshub", "/sspai/index", instances)
    assert selected == "https://ok.rsshub.test/sspai/index"
    assert attempt == 2
    assert parsed is not None
    assert getattr(parsed, "bozo", True) is False


def test_load_rsshub_instances_from_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pool = tmp_path / "rsshub_instances.txt"
    pool.write_text("# comment\nhttps://x.rsshub.test/\nhttps://y.rsshub.test\n", encoding="utf-8")
    monkeypatch.setattr(runner, "RSSHUB_INSTANCES_FILE", pool)
    monkeypatch.delenv("RSSHUB_INSTANCES", raising=False)

    assert runner.load_rsshub_instances() == ["https://x.rsshub.test", "https://y.rsshub.test"]


def test_state_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(runner, "STATE_FILE", state_file)
    payload = {"sent": {"x": {"url": "https://example.com", "ts": "2026-01-01T00:00:00+00:00"}}}

    runner.save_state(payload)
    assert runner.load_state() == payload


def test_stable_id_prefers_entry_id() -> None:
    entry_a = {"id": "same", "link": "https://a", "title": "A"}
    entry_b = {"id": "same", "link": "https://b", "title": "B"}
    assert runner.stable_id(entry_a) == runner.stable_id(entry_b)


def test_passes_filter_include_exclude(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "KEYWORDS_INCLUDE", ["openai"])
    monkeypatch.setattr(runner, "KEYWORDS_EXCLUDE", ["hiring"])
    entry_ok = {"title": "OpenAI releases update"}
    entry_bad = {"title": "OpenAI hiring boom"}

    assert runner.passes_filter(entry_ok) is True
    assert runner.passes_filter(entry_bad) is False


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

    monkeypatch.setattr(runner, "CUBOX_API_URL", "https://cubox.example/api")
    monkeypatch.setattr(runner.requests, "post", fake_post)

    out = runner.cubox_save_url(
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
    monkeypatch.setattr(runner, "CUBOX_API_URL", None)
    with pytest.raises(RuntimeError):
        runner.cubox_save_url(url="https://example.com")


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
    monkeypatch.setattr(runner.requests, "post", fake_post)

    out = runner.analyze_candidates_with_ai(
        [{"eid": "e1", "url": "https://example.com/1", "title": "t", "description": "d"}]
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
    monkeypatch.setattr(runner.requests, "post", lambda *_, **__: Resp())

    out = runner.analyze_candidates_with_ai(
        [{"eid": "e2", "url": "https://example.com/2", "title": "t2", "description": "d2"}]
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
    monkeypatch.setattr(runner.requests, "post", flaky_post)
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)

    out = runner.analyze_candidates_with_ai(
        [{"eid": "e3", "url": "https://example.com/3", "title": "t3", "description": "d3"}]
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
    monkeypatch.setattr(runner.requests, "post", fake_post)

    cands = [
        {"eid": f"e{i}", "url": f"https://example.com/{i}", "title": "t", "description": "d"}
        for i in range(7)
    ]
    out = runner.analyze_candidates_with_ai(cands)
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

    def fake_parse(url: str):  # noqa: ANN001
        assert url == "https://feed.example/rss"
        return SimpleNamespace(bozo=False, entries=entries)

    def fake_save(url: str, title: str, description: str, tags, folder: str):  # noqa: ANN001
        pushed_urls.append((url, title, description, tags, folder))
        return "ok"

    monkeypatch.setattr(runner, "FEEDS_FILE", feeds_file)
    monkeypatch.setattr(runner, "STATE_FILE", state_file)
    monkeypatch.setattr(runner, "MAX_ITEMS_PER_RUN", 1)
    monkeypatch.setattr(runner, "KEYWORDS_INCLUDE", [])
    monkeypatch.setattr(runner, "KEYWORDS_EXCLUDE", [])
    monkeypatch.setattr(runner, "CUBOX_FOLDER", "RSS Inbox")
    monkeypatch.setattr(runner, "ANTHROPIC_AUTH_TOKEN", "")
    monkeypatch.setattr(runner, "ANTHROPIC_MODEL", "")
    monkeypatch.setattr(runner.feedparser, "parse", fake_parse)
    monkeypatch.setattr(runner, "cubox_save_url", fake_save)
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)

    runner.main()

    assert len(pushed_urls) == 1
    assert pushed_urls[0][0] == "https://example.com/1"
    state = runner.load_state()
    assert len(state["sent"]) == 1


def test_write_step_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary_file = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

    runner.write_step_summary(
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
        }
    )

    content = summary_file.read_text(encoding="utf-8")
    assert "RSS2Cubox Run Summary" in content
    assert "| fetched | 10 |" in content
    assert "| ai_kept | 2 |" in content
    assert "| pushed | 2 |" in content
