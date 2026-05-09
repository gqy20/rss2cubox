import json
import os
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from rss2cubox import feed_sources, sync_pipeline
from rss2cubox import metrics
from rss2cubox import runner


class FeedParserDict(dict):
    """A dict subclass that mimics feedparser.util.FeedParserDict for testing."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


def test_load_lines_ignores_blank_and_comment(tmp_path: Path) -> None:
    feeds = tmp_path / "feeds.txt"
    feeds.write_text("# comment\n\nhttps://a.example/rss\n  \nhttps://b.example/rss\n", encoding="utf-8")

    assert feed_sources.load_lines(feeds) == ["https://a.example/rss", "https://b.example/rss"]


def test_load_local_env_file_overwrites_existing_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that .env file has highest priority and overwrites existing env vars."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "IC_API_URL=http://ic.example/api/v1/articles/batch\nEXISTING=from_file\n# comment\nINVALID\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("IC_API_URL", raising=False)
    monkeypatch.setenv("EXISTING", "from_env")

    runner._load_local_env_file(env_file)

    assert os.environ["IC_API_URL"] == "http://ic.example/api/v1/articles/batch"
    # .env overwrites existing env vars (highest priority for local development)
    assert os.environ["EXISTING"] == "from_file"


def test_load_feed_specs_supports_sections(tmp_path: Path) -> None:
    feeds = tmp_path / "feeds.txt"
    feeds.write_text(
        "[rsshub]\n/sspai/index\n\n[direct]\nhttps://example.com/feed.xml\n",
        encoding="utf-8",
    )
    assert feed_sources.load_feed_specs(feeds) == [
        {"kind": "rsshub", "value": "/sspai/index", "label": ""},
        {"kind": "direct", "value": "https://example.com/feed.xml", "label": ""},
    ]


def test_load_feed_specs_supports_inline_label(tmp_path: Path) -> None:
    feeds = tmp_path / "feeds.txt"
    feeds.write_text(
        "[rsshub]\n/bilibili/user/video/123456 # 测试UP主\n",
        encoding="utf-8",
    )
    assert feed_sources.load_feed_specs(feeds) == [
        {"kind": "rsshub", "value": "/bilibili/user/video/123456", "label": "测试UP主"},
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


def test_bilibili_video_browser_uses_bilibili_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RSSHUB_PRIVATE_INSTANCES", "https://private.rsshub.test")
    monkeypatch.setenv("RSSHUB_BILIBILI_INSTANCES", "https://bili.rsshub.test")
    pool = feed_sources.RSSHubInstancePool(instances=["https://private.rsshub.test", "https://general.rsshub.test"])

    assert feed_sources.resolve_feed_urls("rsshub", "/bilibili/user/video-browser/123456", pool) == [
        "https://private.rsshub.test/bilibili/user/video-browser/123456",
        "https://bili.rsshub.test/bilibili/user/video-browser/123456",
        "https://general.rsshub.test/bilibili/user/video-browser/123456",
    ]


def test_bilibili_special_instances_ignore_global_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RSSHUB_PRIVATE_INSTANCES", "https://private.rsshub.test")
    pool = feed_sources.RSSHubInstancePool(instances=["https://private.rsshub.test"], cooldown_seconds=300)
    pool.mark_failure("https://private.rsshub.test")
    events: list[str] = []

    selected, parsed, attempt, _attempts = feed_sources.parse_feed_with_fallback(
        "rsshub",
        "/bilibili/user/video-browser/123456",
        pool,
        fetcher=lambda _url: SimpleNamespace(bozo=False, entries=[{"id": "1"}]),
        log_event=lambda _level, event, **_kwargs: events.append(event),
    )

    assert selected == "https://private.rsshub.test/bilibili/user/video-browser/123456"
    assert parsed is not None
    assert attempt == 1
    assert "feed_candidate_skipped_cooldown" not in events


def test_parse_feed_with_fallback_uses_next_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    instances = ["https://bad.rsshub.test", "https://ok.rsshub.test"]
    pool = feed_sources.RSSHubInstancePool(instances=instances, cooldown_seconds=1)

    def fake_fetch(url: str):  # noqa: ANN001
        if url.startswith("https://bad.rsshub.test"):
            raise RuntimeError("boom")
        return SimpleNamespace(bozo=False, entries=[{"id": "1", "link": "https://example.com/1"}])

    selected, parsed, attempt, _attempts = feed_sources.parse_feed_with_fallback(
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
    monkeypatch.delenv("RSSHUB_PRIVATE_INSTANCES", raising=False)
    monkeypatch.delenv("RSSHUB_INSTANCES", raising=False)

    assert feed_sources.load_rsshub_instances(pool) == ["https://x.rsshub.test", "https://y.rsshub.test"]


def test_state_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_file = tmp_path / "state.json"
    _ = monkeypatch
    payload = {"processed": {"x": {"url": "https://example.com", "created_at": "2026-01-01T00:00:00+00:00"}}}

    sync_pipeline.save_state(state_file, payload)
    assert sync_pipeline.load_state(state_file) == payload


def test_stable_id_prefers_url() -> None:
    # 相同 URL 生成相同的 stable_id（即使 id 不同）
    entry_a = {"id": "v1", "link": "https://arxiv.org/abs/2603.03992", "title": "A"}
    entry_b = {"id": "v2", "link": "https://arxiv.org/abs/2603.03992", "title": "B"}
    assert sync_pipeline.stable_id(entry_a) == sync_pipeline.stable_id(entry_b)

    # 没有 URL 时，回退到 id/guid
    entry_c = {"id": "same-id", "title": "C"}
    entry_d = {"id": "same-id", "title": "D"}
    assert sync_pipeline.stable_id(entry_c) == sync_pipeline.stable_id(entry_d)

    # 没有 URL 和 id 时，回退到 title
    entry_e = {"title": "same-title"}
    entry_f = {"title": "same-title"}
    assert sync_pipeline.stable_id(entry_e) == sync_pipeline.stable_id(entry_f)


def test_passes_filter_include_exclude(monkeypatch: pytest.MonkeyPatch) -> None:
    _ = monkeypatch
    entry_ok = {"title": "OpenAI releases update"}
    entry_bad = {"title": "OpenAI hiring boom"}

    assert sync_pipeline.passes_filter(entry_ok, ["openai"], ["hiring"]) is True
    assert sync_pipeline.passes_filter(entry_bad, ["openai"], ["hiring"]) is False


def test_post_articles_batch_builds_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {}

    class Resp:
        text = '{"ok":true}'

        @staticmethod
        def raise_for_status() -> None:
            return None

    def fake_post(url, json, timeout):  # noqa: ANN001
        calls["url"] = url
        calls["json"] = json
        calls["timeout"] = timeout
        return Resp()

    out = sync_pipeline.post_articles_batch(
        api_url="https://ic.example/api/v1/articles/batch",
        request_post=fake_post,
        articles=[
            {
                "source_type": "gqy",
                "source_feed_id": "feed-1",
                "source_feed_name": "供应情报",
                "source_article_id": "article-1",
                "title": "t",
                "url": "https://example.com/post",
                "pic_url": "https://example.com/post.png",
                "description": "d",
                "publish_time": "2026-01-01T00:00:00+00:00",
                "tags": ["news"],
                "reason": "r",
                "actionable": "a",
                "hidden_signal": "h",
            }
        ],
    )

    assert out == '{"ok":true}'
    assert calls["url"] == "https://ic.example/api/v1/articles/batch"
    assert calls["timeout"] == 30
    assert calls["json"] == {
        "articles": [
            {
                "source_type": "gqy",
                "source_feed_id": "feed-1",
                "source_feed_name": "供应情报",
                "source_article_id": "article-1",
                "title": "t",
                "url": "https://example.com/post",
                "pic_url": "https://example.com/post.png",
                "description": "d",
                "publish_time": "2026-01-01T00:00:00+00:00",
                "tags": ["news"],
                "reason": "r",
                "actionable": "a",
                "hidden_signal": "h",
            }
        ]
    }


def test_post_articles_in_chunks_splits_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    batches = []

    def fake_post_articles_batch(*, api_url: str | None, request_post, articles):  # noqa: ANN001
        _ = request_post
        batches.append((api_url, articles))
        return "ok"

    monkeypatch.setattr(sync_pipeline, "post_articles_batch", fake_post_articles_batch)

    out = sync_pipeline.post_articles_in_chunks(
        api_url="https://ic.example/api/v1/articles/batch",
        request_post=lambda *args, **kwargs: None,
        articles=[{"id": "1"}, {"id": "2"}, {"id": "3"}],
        chunk_size=2,
    )

    assert out == ["ok", "ok"]
    assert batches == [
        ("https://ic.example/api/v1/articles/batch", [{"id": "1"}, {"id": "2"}]),
        ("https://ic.example/api/v1/articles/batch", [{"id": "3"}]),
    ]


def test_post_articles_batch_requires_api_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _ = monkeypatch
    with pytest.raises(RuntimeError):
        sync_pipeline.post_articles_batch(api_url=None, request_post=lambda *args, **kwargs: None, articles=[])


def test_load_ic_state_builds_processed_and_feed_cursor() -> None:
    class Resp:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict:
            return {
                "data": {
                    "list": [
                        {
                            "url": "https://example.com/a?utm_source=test",
                            "publish_time": "2026-03-20T10:00:00+00:00",
                            "source_feed_id": "feed-a",
                        },
                        {
                            "url": "https://example.com/b",
                            "publish_time": "2026-03-20T12:00:00+00:00",
                            "source_feed_id": "feed-a",
                        },
                    ]
                }
            }

    calls = []

    def fake_get(url, params, timeout):  # noqa: ANN001
        calls.append((url, params, timeout))
        if params["offset"] > 0:
            class EmptyResp(Resp):
                @staticmethod
                def json() -> dict:
                    return {"data": {"list": []}}
            return EmptyResp()
        return Resp()

    # Mock load_local_state to return empty so IC API is used
    with unittest.mock.patch.object(sync_pipeline, "load_local_state", return_value=({}, {})):
        processed, feed_cursor = sync_pipeline.load_ic_state(
            api_url="https://ic.example/api/v1/articles/batch",
            source_type="gqy",
            request_get=fake_get,
            page_size=2,
        )

    assert len(processed) == 2
    assert sync_pipeline.stable_id({"link": "https://example.com/a"}) in processed
    assert feed_cursor == {"feed-a": "2026-03-20T12:00:00+00:00"}
    assert calls[0][0] == "https://ic.example/api/v1/articles"
    assert calls[0][1]["source_type"] == "gqy"


def test_build_processed_article_maps_to_ic_fields() -> None:
    article = sync_pipeline.build_processed_article(
        item={
            "eid": "e1",
            "source_feed": "https://feed.example/rss",
            "source_label": "供应情报",
            "source_article_id": "src-1",
            "title": "标题",
            "url": "https://example.com/post",
            "cover_url": "https://example.com/post.png",
            "description": "原始摘要",
            "publish_time": "2026-03-19T13:18:31.612345+00:00",
        },
        analysis={
            "reason": "命中关键主题",
            "actionable": "建议跟进",
            "hidden_signal": "存在供应链变化信号",
            "tags": ["a", "b"],
            "core_event": "情报文章",
            "content_source": "full_text",
            "signal_type": 3,
            "evidence_type": 1,
            "evidence_strength": 4,
            "novelty_score": 3,
            "impact_horizon": 2,
            "audience": [2, 3],
            "market_stage": 4,
            "confidence": 4,
            "entities": ["OpenAI", "Codex"],
            "cluster_hint": "异步软件工程代理",
            "watch_keywords": ["coding agent", "CI automation"],
            "prediction": "未来30天会出现更多异步代码代理进入工程流程。",
            "disconfirming_evidence": "如果没有真实团队案例则降级。",
        },
        now_iso="2026-03-20T00:00:00+00:00",
        source_type="gqy",
    )

    assert article == {
        "id": "e1",
        "source_type": "gqy",
        "source_feed_id": "https://feed.example/rss",
        "source_feed_name": "供应情报",
        "source_article_id": "src-1",
        "title": "标题",
        "url": "https://example.com/post",
        "pic_url": "https://example.com/post.png",
        "description": "情报文章",
        "publish_time": "2026-03-19T13:18:31.612345+00:00",
        "tags": ["a", "b"],
        "importance_score": 3,
        "reason": "命中关键主题",
        "actionable": "建议跟进",
        "hidden_signal": "存在供应链变化信号",
        "content_source": "full_text",
        "signal_type": 3,
        "evidence_type": 1,
        "evidence_strength": 4,
        "novelty_score": 3,
        "impact_horizon": 2,
        "audience": [2, 3],
        "market_stage": 4,
        "confidence": 4,
        "entities": ["OpenAI", "Codex"],
        "cluster_hint": "异步软件工程代理",
        "watch_keywords": ["coding agent", "CI automation"],
        "prediction": "未来30天会出现更多异步代码代理进入工程流程。",
        "disconfirming_evidence": "如果没有真实团队案例则降级。",
        "enrich_meta": {},
        "exported": False,
        "exported_at": "",
        "created_at": "2026-03-20T00:00:00+00:00",
        "updated_at": "2026-03-20T00:00:00+00:00",
    }


def test_build_processed_article_omits_invalid_signal_codes() -> None:
    article = sync_pipeline.build_processed_article(
        item={
            "eid": "e1",
            "source_feed": "feed",
            "title": "标题",
            "url": "https://example.com/post",
            "description": "原始摘要",
            "publish_time": "2026-03-19T13:18:31.612345+00:00",
        },
        analysis={
            "reason": "命中关键主题",
            "actionable": "建议跟进",
            "hidden_signal": "存在供应链变化信号",
            "tags": ["a"],
            "core_event": "情报文章",
            "signal_type": 99,
            "evidence_strength": 0,
            "audience": [2, 99, "bad"],
        },
        now_iso="2026-03-20T00:00:00+00:00",
        source_type="gqy",
    )

    assert "signal_type" not in article
    assert "evidence_strength" not in article
    assert article["audience"] == [2]


def test_has_signal_analysis_rejects_empty_seed_analysis() -> None:
    assert sync_pipeline.has_signal_analysis({
        "reason": "",
        "hidden_signal": "",
        "actionable": "",
        "tags": [],
        "core_event": "",
    }) is False
    assert sync_pipeline.has_signal_analysis({"hidden_signal": "存在真实变化"}) is True


def test_main_dedup_and_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feeds_file = tmp_path / "feeds.txt"
    feeds_file.write_text("https://feed.example/rss\n", encoding="utf-8")

    entries = [
        {"id": "1", "link": "https://example.com/1", "title": "First", "summary": "A"},
        {"id": "1", "link": "https://example.com/1", "title": "First duplicate", "summary": "A2"},
        {"id": "2", "link": "https://example.com/2", "title": "Second", "summary": "B"},
    ]

    posted_batches = []

    def fake_fetch_and_check_update(url: str, **kwargs):  # noqa: ANN001
        # Returns (parsed, was_modified) tuple - always fetch full content
        assert url == "https://feed.example/rss"
        # Return structure matching feedparser.parse() output
        return FeedParserDict(
            bozo=False,
            entries=[FeedParserDict(e) for e in entries],
            feed=FeedParserDict(updated="Sat, 02 May 2026 13:00:00 +0800")
        ), True

    def fake_post_articles(api_url: str, request_post, articles):  # noqa: ANN001
        _ = request_post
        posted_batches.append((api_url, articles))
        return "ok"

    monkeypatch.setattr(runner, "FEEDS_FILE", feeds_file)
    monkeypatch.setattr(runner, "MAX_ITEMS_PER_RUN", 1)
    monkeypatch.setattr(runner, "KEYWORDS_INCLUDE", [])
    monkeypatch.setattr(runner, "KEYWORDS_EXCLUDE", [])
    monkeypatch.setattr(runner, "IC_API_URL", "https://fake.api.com/api/v1/articles/batch")
    monkeypatch.setattr(runner, "IC_PUSH_ENABLED", True)
    monkeypatch.setattr(runner, "IC_SOURCE_TYPE", "gqy")
    monkeypatch.setattr(runner.sync_pipeline, "load_ic_state", lambda **kwargs: ({}, {}))
    monkeypatch.setattr(feed_sources, "fetch_and_check_update", fake_fetch_and_check_update)
    monkeypatch.setattr(runner.enrich_agent, "analyze_candidates_with_agent", lambda **kwargs: {
        kwargs["candidates"][0]["eid"]: {
            "reason": "高价值",
            "actionable": "跟进",
            "hidden_signal": "信号",
            "tags": ["rss"],
            "core_event": "First",
        }
    })
    monkeypatch.setattr(
        runner.sync_pipeline,
        "post_articles_in_chunks",
        lambda **kwargs: [fake_post_articles(kwargs["api_url"], kwargs["request_post"], kwargs["articles"])],
    )
    monkeypatch.setattr(runner, "run_global_analysis", lambda **kwargs: None)
    monkeypatch.setattr(runner, "save_articles", lambda **kwargs: None)
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)

    runner.main()

    assert len(posted_batches) == 1
    assert posted_batches[0][0] == "https://fake.api.com/api/v1/articles/batch"
    assert posted_batches[0][1][0]["url"] == "https://example.com/1"


def test_main_ic_push_disabled_skips_ic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """IC_PUSH_ENABLED=false 时跳过 IC 推送，只写本地 DB。"""
    feeds_file = tmp_path / "feeds.txt"
    feeds_file.write_text("https://feed.example/rss\n", encoding="utf-8")

    entries = [
        {"id": "1", "link": "https://example.com/1", "title": "First", "summary": "A"},
    ]

    ic_posted = []
    local_saved = []

    def fake_fetch_and_check_update(url: str, **kwargs):  # noqa: ANN001
        return FeedParserDict(
            bozo=False,
            entries=[FeedParserDict(e) for e in entries],
            feed=FeedParserDict(updated="Sat, 02 May 2026 13:00:00 +0800")
        ), True

    def fake_post_articles_in_chunks(**kwargs):  # noqa: ANN001
        ic_posted.append(kwargs)
        return ["ok"]

    def fake_save_articles(records):  # noqa: ANN001
        local_saved.extend(records)

    monkeypatch.setattr(runner, "FEEDS_FILE", feeds_file)
    monkeypatch.setattr(runner, "MAX_ITEMS_PER_RUN", 20)
    monkeypatch.setattr(runner, "KEYWORDS_INCLUDE", [])
    monkeypatch.setattr(runner, "KEYWORDS_EXCLUDE", [])
    monkeypatch.setattr(runner, "IC_API_URL", "https://fake.api.com/api/v1/articles/batch")
    monkeypatch.setattr(runner, "IC_PUSH_ENABLED", False)
    monkeypatch.setattr(runner, "IC_SOURCE_TYPE", "gqy")
    monkeypatch.setattr(runner.sync_pipeline, "load_ic_state", lambda **kwargs: ({}, {}))
    monkeypatch.setattr(feed_sources, "fetch_and_check_update", fake_fetch_and_check_update)
    monkeypatch.setattr(runner.enrich_agent, "analyze_candidates_with_agent", lambda **kwargs: {
        item["eid"]: {
            "reason": "高价值",
            "actionable": "跟进",
            "hidden_signal": "信号",
            "tags": ["rss"],
            "core_event": item["title"],
        }
        for item in kwargs["candidates"]
    })
    monkeypatch.setattr(runner.sync_pipeline, "post_articles_in_chunks", fake_post_articles_in_chunks)
    monkeypatch.setattr(runner, "save_articles", fake_save_articles)
    monkeypatch.setattr(runner, "run_global_analysis", lambda **kwargs: None)
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)

    runner.main()

    assert len(ic_posted) == 0
    assert len(local_saved) == 1
    assert local_saved[0]["url"] == "https://example.com/1"


def test_main_feed_cursor_prefilter_without_persistence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feeds_file = tmp_path / "feeds.txt"
    feed_url = "https://feed.example/rss"
    feeds_file.write_text(f"{feed_url}\n", encoding="utf-8")

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

    posted_batches = []

    def fake_fetch_and_check_update(url: str, **kwargs):  # noqa: ANN001
        assert url == feed_url
        return FeedParserDict(
            bozo=False,
            entries=[FeedParserDict(e) for e in entries],
            feed=FeedParserDict(updated="Sat, 02 May 2026 13:00:00 +0800")
        ), True

    def fake_post_articles(api_url: str, request_post, articles):  # noqa: ANN001
        _ = (api_url, request_post)
        posted_batches.append(articles)
        return "ok"

    monkeypatch.setattr(runner, "FEEDS_FILE", feeds_file)
    monkeypatch.setattr(runner, "MAX_ITEMS_PER_RUN", 20)
    monkeypatch.setattr(runner, "KEYWORDS_INCLUDE", [])
    monkeypatch.setattr(runner, "KEYWORDS_EXCLUDE", [])
    monkeypatch.setattr(runner, "IC_API_URL", "https://fake.api.com/api/v1/articles/batch")
    monkeypatch.setattr(runner, "IC_PUSH_ENABLED", True)
    monkeypatch.setattr(runner, "IC_SOURCE_TYPE", "gqy")
    monkeypatch.setattr(runner, "FEED_CURSOR_LOOKBACK_HOURS", 24)
    monkeypatch.setattr(
        runner.sync_pipeline,
        "load_ic_state",
        lambda **kwargs: ({}, {feed_url: "2026-01-10T00:00:00+00:00"}),
    )
    monkeypatch.setattr(feed_sources, "fetch_and_check_update", fake_fetch_and_check_update)
    monkeypatch.setattr(runner.enrich_agent, "analyze_candidates_with_agent", lambda **kwargs: {
        item["eid"]: {
            "reason": "高价值",
            "actionable": "跟进",
            "hidden_signal": "信号",
            "tags": ["rss"],
            "core_event": item["title"],
        }
        for item in kwargs["candidates"]
    })
    monkeypatch.setattr(
        runner.sync_pipeline,
        "post_articles_in_chunks",
        lambda **kwargs: [fake_post_articles(kwargs["api_url"], kwargs["request_post"], kwargs["articles"])],
    )
    monkeypatch.setattr(runner, "run_global_analysis", lambda **kwargs: None)
    monkeypatch.setattr(runner, "save_articles", lambda **kwargs: None)
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)

    runner.main()

    posted_urls = [article["url"] for batch in posted_batches for article in batch]
    assert "https://example.com/new" in posted_urls
    assert "https://example.com/nodate" in posted_urls
    assert "https://example.com/old" not in posted_urls


def test_main_run_seen_dedup_across_feeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feeds_file = tmp_path / "feeds.txt"
    feed_a = "https://feed-a.example/rss"
    feed_b = "https://feed-b.example/rss"
    feeds_file.write_text(f"{feed_a}\n{feed_b}\n", encoding="utf-8")

    shared_entry = {"id": "same-id", "link": "https://example.com/shared", "title": "Shared", "summary": "A"}
    entries_by_feed = {
        feed_a: [shared_entry],
        feed_b: [shared_entry],
    }
    posted_batches = []

    def fake_fetch_and_check_update(url: str, **kwargs):  # noqa: ANN001
        return FeedParserDict(
            bozo=False,
            entries=[FeedParserDict(e) for e in entries_by_feed[url]],
            feed=FeedParserDict(updated="Sat, 02 May 2026 13:00:00 +0800")
        ), True

    def fake_post_articles(api_url: str, request_post, articles):  # noqa: ANN001
        _ = (api_url, request_post)
        posted_batches.append(articles)
        return "ok"

    monkeypatch.setattr(runner, "FEEDS_FILE", feeds_file)
    monkeypatch.setattr(runner, "MAX_ITEMS_PER_RUN", 20)
    monkeypatch.setattr(runner, "KEYWORDS_INCLUDE", [])
    monkeypatch.setattr(runner, "KEYWORDS_EXCLUDE", [])
    monkeypatch.setattr(runner, "IC_API_URL", "https://fake.api.com/api/v1/articles/batch")
    monkeypatch.setattr(runner, "IC_PUSH_ENABLED", True)
    monkeypatch.setattr(runner, "IC_SOURCE_TYPE", "gqy")
    monkeypatch.setattr(runner.sync_pipeline, "load_ic_state", lambda **kwargs: ({}, {}))
    monkeypatch.setattr(feed_sources, "fetch_and_check_update", fake_fetch_and_check_update)
    monkeypatch.setattr(runner.enrich_agent, "analyze_candidates_with_agent", lambda **kwargs: {
        item["eid"]: {
            "reason": "高价值",
            "actionable": "跟进",
            "hidden_signal": "信号",
            "tags": ["rss"],
            "core_event": item["title"],
        }
        for item in kwargs["candidates"]
    })
    monkeypatch.setattr(
        runner.sync_pipeline,
        "post_articles_in_chunks",
        lambda **kwargs: [fake_post_articles(kwargs["api_url"], kwargs["request_post"], kwargs["articles"])],
    )
    monkeypatch.setattr(runner, "run_global_analysis", lambda **kwargs: None)
    monkeypatch.setattr(runner, "save_articles", lambda **kwargs: None)
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)

    runner.main()

    posted_urls = [article["url"] for batch in posted_batches for article in batch]
    assert posted_urls == ["https://example.com/shared"]


def test_main_skips_articles_already_in_ic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feeds_file = tmp_path / "feeds.txt"
    feed_url = "https://feed.example/rss"
    feeds_file.write_text(f"{feed_url}\n", encoding="utf-8")

    entries = [
        {"id": "1", "link": "https://example.com/existing", "title": "Existing", "summary": "A"},
        {"id": "2", "link": "https://example.com/new", "title": "New", "summary": "B"},
    ]
    posted_batches = []
    existing_eid = sync_pipeline.stable_id({"link": "https://example.com/existing"})

    def fake_fetch_and_check_update(url: str, **kwargs):  # noqa: ANN001
        assert url == feed_url
        return FeedParserDict(bozo=False, entries=[FeedParserDict(e) for e in entries], feed=FeedParserDict(updated="Sat, 02 May 2026 13:00:00 +0800")), True

    def fake_post_articles(api_url: str, request_post, articles):  # noqa: ANN001
        _ = (api_url, request_post)
        posted_batches.append(articles)
        return "ok"

    monkeypatch.setattr(runner, "FEEDS_FILE", feeds_file)
    monkeypatch.setattr(runner, "MAX_ITEMS_PER_RUN", 20)
    monkeypatch.setattr(runner, "KEYWORDS_INCLUDE", [])
    monkeypatch.setattr(runner, "KEYWORDS_EXCLUDE", [])
    monkeypatch.setattr(runner, "IC_API_URL", "https://fake.api.com/api/v1/articles/batch")
    monkeypatch.setattr(runner, "IC_PUSH_ENABLED", True)
    monkeypatch.setattr(runner, "IC_SOURCE_TYPE", "gqy")
    monkeypatch.setattr(
        runner.sync_pipeline,
        "load_ic_state",
        lambda **kwargs: ({existing_eid: {"id": existing_eid, "exported": True}}, {}),
    )
    monkeypatch.setattr(feed_sources, "fetch_and_check_update", fake_fetch_and_check_update)
    monkeypatch.setattr(runner.enrich_agent, "analyze_candidates_with_agent", lambda **kwargs: {
        item["eid"]: {
            "reason": "高价值",
            "actionable": "跟进",
            "hidden_signal": "信号",
            "tags": ["rss"],
            "core_event": item["title"],
        }
        for item in kwargs["candidates"]
    })
    monkeypatch.setattr(
        runner.sync_pipeline,
        "post_articles_in_chunks",
        lambda **kwargs: [fake_post_articles(kwargs["api_url"], kwargs["request_post"], kwargs["articles"])],
    )
    monkeypatch.setattr(runner, "run_global_analysis", lambda **kwargs: None)
    monkeypatch.setattr(runner, "save_articles", lambda **kwargs: None)
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)

    runner.main()

    posted_urls = [article["url"] for batch in posted_batches for article in batch]
    assert posted_urls == ["https://example.com/new"]


def test_run_json_agent_env_none_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """env=None 不应导致 'NoneType object is not a mapping' 崩溃。"""
    from rss2cubox.agent_sdk_runner import run_json_agent
    import inspect

    source = inspect.getsource(run_json_agent)
    # 防御性检查：env= 传入 ClaudeAgentOptions 时必须用 None 安全模式
    assert ("env=env or {}" in source or "dict(env) if env else" in source), \
        "env 参数应使用 None 安全模式防止崩溃"


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
    blocked_feed = "https://blocked.example/rss"
    ok_feed = "https://ok.example/rss"
    feeds_file.write_text(f"{blocked_feed}\n{ok_feed}\n", encoding="utf-8")

    fetched = []
    posted_batches = []

    def fake_fetch_and_check_update(url: str, **kwargs):  # noqa: ANN001
        fetched.append(url)
        entry = {"id": url, "link": f"{url}/1", "title": "t", "summary": "s"}
        return FeedParserDict(bozo=False, entries=[FeedParserDict(entry)], feed=FeedParserDict(updated="Sat, 02 May 2026 13:00:00 +0800")), True

    def fake_post_articles(api_url: str, request_post, articles):  # noqa: ANN001
        _ = (api_url, request_post)
        posted_batches.append(articles)
        return "ok"

    monkeypatch.setattr(runner, "FEEDS_FILE", feeds_file)
    monkeypatch.setattr(runner, "MAX_ITEMS_PER_RUN", 20)
    monkeypatch.setattr(runner, "KEYWORDS_INCLUDE", [])
    monkeypatch.setattr(runner, "KEYWORDS_EXCLUDE", [])
    monkeypatch.setattr(runner, "IC_API_URL", "https://fake.api.com/api/v1/articles/batch")
    monkeypatch.setattr(runner, "IC_PUSH_ENABLED", True)
    monkeypatch.setattr(runner, "IC_SOURCE_TYPE", "gqy")
    monkeypatch.setattr(runner, "FEED_FETCH_CONCURRENCY", 4)
    monkeypatch.setattr(runner.sync_pipeline, "load_ic_state", lambda **kwargs: ({}, {}))
    monkeypatch.setattr(feed_sources, "fetch_and_check_update", fake_fetch_and_check_update)
    monkeypatch.setattr(runner.enrich_agent, "analyze_candidates_with_agent", lambda **kwargs: {
        item["eid"]: {
            "reason": "高价值",
            "actionable": "跟进",
            "hidden_signal": "信号",
            "tags": ["rss"],
            "core_event": item["title"],
        }
        for item in kwargs["candidates"]
    })
    monkeypatch.setattr(
        runner.sync_pipeline,
        "post_articles_in_chunks",
        lambda **kwargs: [fake_post_articles(kwargs["api_url"], kwargs["request_post"], kwargs["articles"])],
    )
    monkeypatch.setattr(runner, "run_global_analysis", lambda **kwargs: None)
    monkeypatch.setattr(runner, "save_articles", lambda **kwargs: None)
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)

    runner.main()

    assert blocked_feed in fetched
    assert ok_feed in fetched
    posted_urls = sorted(article["url"] for batch in posted_batches for article in batch)
    assert posted_urls == [f"{blocked_feed}/1", f"{ok_feed}/1"]
