from pathlib import Path
from types import SimpleNamespace

import pytest

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
