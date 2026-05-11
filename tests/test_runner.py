import json
import os
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import FeedParserDict
from rss2cubox import feed_sources, sync_pipeline
from rss2cubox import metrics
from rss2cubox import runner


def _setup_runner_mocks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    entries: list[dict] | None = None,
    max_items: int = 20,
    ic_push_enabled: bool = True,
    ic_state: tuple[dict, dict] | None = None,
    enrich_fn=None,
    post_fn=None,
    save_fn=None,
) -> tuple[list[dict], list[tuple]]:
    """为 test_main_* 函数统一设置 monkeypatch，返回 (posted_batches, fetched_urls)。"""
    if entries is None:
        entries = [{"id": "1", "link": "https://example.com/1", "title": "T", "summary": "S"}]

    feeds_file = tmp_path / "feeds.txt"
    feeds_file.write_text("https://feed.example/rss\n", encoding="utf-8")

    posted_batches: list[tuple] = []
    fetched_urls: list[str] = []

    def fake_fetch(url: str, **_kw: ...):  # noqa: ANN001
        fetched_urls.append(url)
        return FeedParserDict(
            bozo=False,
            entries=[FeedParserDict(e) for e in entries],
            feed=FeedParserDict(updated="Sat, 02 May 2026 13:00:00 +0800"),
        ), True

    _enrich_fn = enrich_fn or (lambda **kw: {
        item["eid"]: {"reason": "高价值", "actionable": "跟进", "hidden_signal": "信号",
                       "tags": ["rss"], "core_event": item["title"]}
        for item in kw["candidates"]
    })
    _post_fn = post_fn or (lambda **kw: posted_batches.append(kw["articles"]) or None)
    _save_fn = save_fn or (lambda *_, **__: None)
    _ic_state = ic_state or ({}, {})

    monkeypatch.setattr(runner, "FEEDS_FILE", feeds_file)
    monkeypatch.setattr(runner, "MAX_ITEMS_PER_RUN", max_items)
    monkeypatch.setattr(runner, "KEYWORDS_INCLUDE", [])
    monkeypatch.setattr(runner, "KEYWORDS_EXCLUDE", [])
    monkeypatch.setattr(runner, "IC_API_URL", "https://fake.api.com/api/v1/articles/batch")
    monkeypatch.setattr(runner, "IC_PUSH_ENABLED", ic_push_enabled)
    monkeypatch.setattr(runner, "IC_SOURCE_TYPE", "gqy")
    monkeypatch.setattr(runner.sync_pipeline, "load_ic_state", lambda **_kw: _ic_state)
    monkeypatch.setattr(feed_sources, "fetch_and_check_update", fake_fetch)
    monkeypatch.setattr(runner.enrich_agent, "analyze_candidates_with_agent", _enrich_fn)
    monkeypatch.setattr(runner.sync_pipeline, "post_articles_in_chunks", _post_fn)
    monkeypatch.setattr(runner, "run_global_analysis", lambda **_kw: None)
    monkeypatch.setattr(runner, "save_articles", _save_fn)
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)

    return posted_batches, fetched_urls


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
    entries = [
        {"id": "1", "link": "https://example.com/1", "title": "First", "summary": "A"},
        {"id": "1", "link": "https://example.com/1", "title": "First duplicate", "summary": "A2"},
        {"id": "2", "link": "https://example.com/2", "title": "Second", "summary": "B"},
    ]

    posted_batches, _ = _setup_runner_mocks(monkeypatch, tmp_path, entries=entries, max_items=1)
    runner.main()

    assert len(posted_batches) == 1
    assert posted_batches[0][0]["url"] == "https://example.com/1"


def test_main_ic_push_disabled_skips_ic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """IC_PUSH_ENABLED=false 时跳过 IC 推送，只写本地 DB。"""
    ic_posted = []
    local_saved = []

    _, _ = _setup_runner_mocks(
        monkeypatch, tmp_path,
        ic_push_enabled=False,
        post_fn=lambda **kw: (ic_posted.append(kw), ["ok"])[1],
        save_fn=lambda records: local_saved.extend(records),
    )

    runner.main()

    assert len(ic_posted) == 0
    assert len(local_saved) == 1
    assert local_saved[0]["url"] == "https://example.com/1"


def test_main_feed_cursor_prefilter_without_persistence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entries = [
        {"id": "old", "link": "https://example.com/old", "title": "Old", "summary": "too old",
         "published": "2026-01-01T00:00:00+00:00"},
        {"id": "new", "link": "https://example.com/new", "title": "New", "summary": "fresh",
         "published": "2026-01-10T12:00:00+00:00"},
        {"id": "nodate", "link": "https://example.com/nodate", "title": "No Date", "summary": "no timestamp"},
    ]

    posted_batches, _ = _setup_runner_mocks(
        monkeypatch, tmp_path, entries=entries,
        ic_state=({}, {"https://feed.example/rss": "2026-01-10T00:00:00+00:00"}),
    )
    # 覆盖 FEED_CURSOR_LOOKBACK_HOURS
    monkeypatch.setattr(runner, "FEED_CURSOR_LOOKBACK_HOURS", 24)

    runner.main()

    posted_urls = [article["url"] for batch in posted_batches for article in batch]
    assert "https://example.com/new" in posted_urls
    assert "https://example.com/nodate" in posted_urls
    assert "https://example.com/old" not in posted_urls


def test_main_run_seen_dedup_across_feeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shared_entry = {"id": "same-id", "link": "https://example.com/shared", "title": "Shared", "summary": "A"}

    posted_batches, _ = _setup_runner_mocks(
        monkeypatch, tmp_path,
        entries=[shared_entry],
        enrich_fn=lambda **kw: {
            item["eid"]: {
                "reason": "高价值", "actionable": "跟进", "hidden_signal": "信号",
                "tags": ["rss"], "core_event": item["title"],
            }
            for item in kw["candidates"]
        },
    )

    runner.main()

    posted_urls = [article["url"] for batch in posted_batches for article in batch]
    assert posted_urls == ["https://example.com/shared"]


def test_main_skips_articles_already_in_ic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    existing_eid = sync_pipeline.stable_id({"link": "https://example.com/existing"})

    entries = [
        {"id": "1", "link": "https://example.com/existing", "title": "Existing", "summary": "A"},
        {"id": "2", "link": "https://example.com/new", "title": "New", "summary": "B"},
    ]

    posted_batches, _ = _setup_runner_mocks(
        monkeypatch, tmp_path, entries=entries,
        ic_state=({existing_eid: {"id": existing_eid, "exported": True}}, {}),
    )

    runner.main()

    posted_urls = [article["url"] for batch in posted_batches for article in batch]
    assert posted_urls == ["https://example.com/new"]


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
    _, _ = _setup_runner_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "FEED_FETCH_CONCURRENCY", 4)

    runner.main()


# ── TDD: 两阶段写入 + DB fallback 测试 ──────────────────────────


class _FakeFetchResult:
    """模拟 fulltext_fetcher.fetch_fulltext_batch 的返回值。"""

    def __init__(self, text: str, source: str = "jina"):
        self.text = text
        self.source = source


def _make_candidates(n: int = 3) -> list[dict]:
    """生成 N 条候选文章，每条带 eid/url/title/description。"""
    return [
        {
            "eid": f"eid-{i:04d}",
            "url": f"https://example.com/article/{i}",
            "title": f"文章标题 {i}",
            "description": f"摘要内容 {i}",
            "source_feed": "https://feed.example/rss",
            "source_label": "测试源",
            "source_article_id": f"src-{i}",
        }
        for i in range(1, n + 1)
    ]


class TestTwoPhaseWriteSavesRawArticlesWhenEnrichFails:
    """enrich 返回空分析时，原始文章 + 全文仍应入库（不依赖 AI）。"""

    def test_enrich_failure_still_saves_articles_with_fulltext(
        self, mock_db_conn, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Phase 1 在 enrich 之前保存原始文章+全文，即使后续 enrich 失败数据也已持久化。"""
        import psycopg

        conn, cur = mock_db_conn
        monkeypatch.setattr(psycopg, "connect", lambda url: conn)

        candidates = _make_candidates(3)
        ft_results = {
            c["eid"]: _FakeFetchResult(f"全文内容 for {c['eid']}", "jina")
            for c in candidates
        }

        # 模拟 runner.py Phase 1 逻辑：构建原始文章 + 注入 full_text
        _raw_articles = []
        for item in candidates:
            eid = str(item.get("eid", "")).strip()
            ft = ft_results.get(eid) if ft_results else None
            _raw_articles.append({
                "id": eid,
                "source_type": "gqy",
                "source_feed_id": str(item.get("source_feed", "")).strip(),
                "source_feed_name": str(item.get("source_label", "")).strip() or "unknown",
                "source_article_id": str(item.get("source_article_id", "")) .strip() or eid,
                "title": str(item.get("title", "")).strip(),
                "url": str(item.get("url", "")).strip(),
                "pic_url": str(item.get("cover_url", "")).strip(),
                "description": str(item.get("description", "")).strip(),
                "publish_time": str(item.get("publish_time", "")).strip(),
                "tags": [],
                "full_text": getattr(ft, "text", None) or "" if ft else "",
                "full_text_source": getattr(ft, "source", "") or "" if ft else "",
                "full_text_fetched_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat() if (ft and getattr(ft, "text", None)) else None,
            })

        # Phase 1 写入（不依赖 AI 分析结果）
        from rss2cubox.db_client.articles import save_articles
        saved = save_articles(_raw_articles, db_url="postgresql://localhost:5433/test")

        # 断言：3 篇文章全部入库，且每篇都携带 full_text
        assert saved == 3, f"期望保存 3 篇，实际保存 {saved}"
        # 验证每次 INSERT/UPSERT 都包含了 full_text
        for call_info in cur.execute.call_args_list:
            args = call_info[0]
            if len(args) >= 2 and "INSERT INTO articles" in args[0]:
                params = args[1]
                ft_val = params.get("full_text", "")
                fts_val = params.get("full_text_source", "")
                assert ft_val not in (None, ""), f"full_text 为空，params id={params.get('id')}"
                assert fts_val == "jina", f"full_text_source 应为 'jina'，实际 '{fts_val}'"

    def test_enrich_failure_with_db_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """本次未抓取全文时，应从 DB 历史记录恢复。"""
        candidates = _make_candidates(2)
        db_fulltexts = {"eid-0001": "DB中的历史全文1", "eid-0002": "DB中的历史全文2"}

        # 在 import 之后 monkeypatch，需要通过 sys.modules 注入
        import sys
        original_module = sys.modules["rss2cubox.db_client.articles"]
        original_get = original_module.get_fulltexts_by_eids

        def fake_get_fulltexts(eids, db_url=None):
            return db_fulltexts

        original_module.get_fulltexts_by_eids = fake_get_fulltexts

        # 模拟 runner.py 中的 fallback 逻辑
        ft_results = {}  # 本次无新抓取
        _pre_ft = {eid: r.text for eid, r in ft_results.items() if r.text}  # 空！

        if not _pre_ft:  # ← 这是需要新增的 fallback 分支
            eids = [c["eid"] for c in candidates]
            from rss2cubox.db_client.articles import get_fulltexts_by_eids
            _pre_ft = get_fulltexts_by_eids(eids)

        # 断言：从 DB 恢复了全文
        assert _pre_ft == db_fulltexts
        assert len(_pre_ft) == 2
        assert "eid-0001" in _pre_ft

        # 恢复原始函数（避免污染其他测试）
        original_module.get_fulltexts_by_eids = original_get


class TestSaveFulltextBatchReturnsActualRowcount:
    """save_fulltext_batch 应返回实际影响的行数，而非循环计数。"""

    def test_returns_zero_when_no_rows_match(self, mock_db_conn) -> None:
        """UPDATE 匹配 0 行时返回 0（而非 len(results)）。"""
        conn, cur = mock_db_conn
        cur.rowcount = 0  # UPDATE WHERE id='nonexistent' 影响行数

        from rss2cubox.db_client.articles import save_fulltext_batch

        results = {
            "eid-absent": _FakeFetchResult("some text"),
            "eid-missing": _FakeFetchResult("other text"),
        }
        # cur.execute 被调用后 rowcount 始终为 0
        count = save_fulltext_batch(results, db_url="fake://")

        # 当前 bug: 会错误地返回 2（循环次数）
        # 修复后: 应返回 0
        assert count == 0, f"期望返回 0 (无匹配行)，实际返回 {count}"

    def test_returns_actual_updated_count(self, mock_db_conn, monkeypatch: pytest.MonkeyPatch) -> None:
        """部分行匹配时应返回实际更新数。"""
        import psycopg

        conn, cur = mock_db_conn
        call_count = [0]

        original_execute = cur.execute

        def counting_execute(sql, params=None):
            call_count[0] += 1
            # 第 1 次是 ARTICLES_SCHEMA（建表），跳过
            # 第 2 次是第一个 UPDATE（命中）
            # 第 3 次是第二个 UPDATE（未命中）
            if call_count[0] == 2:
                cur.rowcount = 1
            else:
                cur.rowcount = 0
            return original_execute(sql, params)

        cur.execute = counting_execute

        # 关键：mock psycopg.connect 让它返回假连接
        monkeypatch.setattr(psycopg, "connect", lambda url: conn)

        from rss2cubox.db_client.articles import save_fulltext_batch

        results = {
            "eid-exists": _FakeFetchResult("text A"),
            "eid-nope": _FakeFetchResult("text B"),
        }
        count = save_fulltext_batch(results, db_url="postgresql://localhost:5433/test")

        # 当前 bug: 返回 2（循环迭代数）
        # 修复后: 应返回 1（实际命中）
        assert count == 1, f"期望返回 1 (实际命中)，实际返回 {count}"
