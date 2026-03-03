from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from rss2cubox import runner


def test_load_lines_ignores_blank_and_comment(tmp_path: Path) -> None:
    feeds = tmp_path / "feeds.txt"
    feeds.write_text("# comment\n\nhttps://a.example/rss\n  \nhttps://b.example/rss\n", encoding="utf-8")

    assert runner.load_lines(feeds) == ["https://a.example/rss", "https://b.example/rss"]


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
