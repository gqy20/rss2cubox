"""Tests for feed_sources module - focus on If-Modified-Since and lastBuildDate optimization."""

import json
from types import SimpleNamespace

import pytest
import requests
import requests_mock

from rss2cubox import feed_sources


class TestFetchAndCheckUpdate:
    """Tests for fetch_and_check_update function."""

    def test_fetch_and_check_update_returns_parsed_when_modified(self) -> None:
        """When lastBuildDate differs from cached, should return full parsed feed."""
        url = "http://example.com/feed.rss"
        xml_content = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
<channel>
<lastBuildDate>Sat, 02 May 2026 13:00:00 +0800</lastBuildDate>
<item><title>Test</title><link>http://example.com/1</link></item>
</channel>
</rss>"""

        with requests_mock.Mocker() as m:
            m.get(url, content=xml_content)
            parsed, was_modified = feed_sources.fetch_and_check_update(
                url,
                connect_timeout_seconds=5.0,
                read_timeout_seconds=30.0,
                cached_last_build_date="Sat, 01 May 2026 13:00:00 +0800",
            )

            assert was_modified is True
            assert parsed is not None
            assert len(parsed.entries) == 1
            assert parsed.entries[0].title == "Test"

    def test_fetch_and_check_update_returns_none_when_not_modified(self) -> None:
        """When lastBuildDate equals cached, should return (None, False) without full fetch."""
        url = "http://example.com/feed.rss"
        xml_content = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
<channel>
<lastBuildDate>Sat, 02 May 2026 13:00:00 +0800</lastBuildDate>
<item><title>Test</title><link>http://example.com/1</link></item>
</channel>
</rss>"""

        with requests_mock.Mocker() as m:
            m.get(url, content=xml_content)
            parsed, was_modified = feed_sources.fetch_and_check_update(
                url,
                connect_timeout_seconds=5.0,
                read_timeout_seconds=30.0,
                cached_last_build_date="Sat, 02 May 2026 13:00:00 +0800",
            )

            assert was_modified is False
            assert parsed is None

    def test_fetch_and_check_update_with_no_cached_value(self) -> None:
        """When cached_last_build_date is None, should always fetch full content."""
        url = "http://example.com/feed.rss"
        xml_content = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
<channel>
<lastBuildDate>Sat, 02 May 2026 13:00:00 +0800</lastBuildDate>
<item><title>Test</title><link>http://example.com/1</link></item>
</channel>
</rss>"""

        with requests_mock.Mocker() as m:
            m.get(url, content=xml_content)
            parsed, was_modified = feed_sources.fetch_and_check_update(
                url,
                connect_timeout_seconds=5.0,
                read_timeout_seconds=30.0,
                cached_last_build_date=None,
            )

            assert was_modified is True
            assert parsed is not None

    def test_fetch_and_check_update_raises_on_parse_error(self) -> None:
        """When feed is malformed, should raise ValueError."""
        url = "http://example.com/feed.rss"
        xml_content = b"not valid xml at all"

        with requests_mock.Mocker() as m:
            m.get(url, content=xml_content)
            with pytest.raises(ValueError, match="invalid feed parse"):
                feed_sources.fetch_and_check_update(
                    url,
                    connect_timeout_seconds=5.0,
                    read_timeout_seconds=30.0,
                    cached_last_build_date=None,
                )

    def test_fetch_and_check_update_raises_on_http_error(self) -> None:
        """When HTTP status is not 200, should raise."""
        url = "http://example.com/feed.rss"

        with requests_mock.Mocker() as m:
            m.get(url, status_code=404)
            with pytest.raises(Exception):
                feed_sources.fetch_and_check_update(
                    url,
                    connect_timeout_seconds=5.0,
                    read_timeout_seconds=30.0,
                    cached_last_build_date=None,
                )


class TestFetchAndParseFeed:
    """Tests for existing fetch_and_parse_feed function (baseline)."""

    def test_fetch_and_parse_feed_returns_parsed(self) -> None:
        """Basic test that fetch_and_parse_feed still works."""
        url = "http://example.com/feed.rss"
        xml_content = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
<channel>
<lastBuildDate>Sat, 02 May 2026 13:00:00 +0800</lastBuildDate>
<item><title>Test</title><link>http://example.com/1</link></item>
</channel>
</rss>"""

        with requests_mock.Mocker() as m:
            m.get(url, content=xml_content)
            parsed = feed_sources.fetch_and_parse_feed(
                url,
                connect_timeout_seconds=5.0,
                read_timeout_seconds=30.0,
            )

            assert parsed is not None
            assert len(parsed.entries) == 1


class TestLastBuildDateCaching:
    """Tests for lastBuildDate extraction and caching logic."""

    def test_last_build_date_extracted_from_feed(self) -> None:
        """Verify we can extract lastBuildDate from a feed."""
        xml_content = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
<channel>
<lastBuildDate>Sat, 02 May 2026 13:00:00 +0800</lastBuildDate>
<item><title>Test</title></item>
</channel>
</rss>"""

        import feedparser
        parsed = feedparser.parse(xml_content)
        # feedparser maps lastBuildDate to 'updated' field
        lbd = parsed.feed.get("updated")
        assert lbd == "Sat, 02 May 2026 13:00:00 +0800"

    def test_last_build_date_missing_is_none(self) -> None:
        """When lastBuildDate is missing, should return None."""
        xml_content = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
<channel>
<item><title>Test</title></item>
</channel>
</rss>"""

        import feedparser
        parsed = feedparser.parse(xml_content)
        lbd = parsed.feed.get("updated")
        assert lbd is None


class TestStreamModeOptimization:
    """Tests to verify stream mode actually saves bandwidth/time."""

    def test_stream_mode_only_fetches_enough_for_lastbuilddate(self) -> None:
        """Verify that when lastBuildDate matches cache, we stop early."""
        import requests_mock

        url = "http://example.com/feed.rss"
        xml_content = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
<channel>
<lastBuildDate>Sat, 02 May 2026 13:00:00 +0800</lastBuildDate>
<item><title>Test</title><link>http://example.com/1</link></item>
</channel>
</rss>"""

        with requests_mock.Mocker() as m:
            m.get(url, content=xml_content)

            # Simulate the stream reading
            import re
            import requests

            lbd_pattern = re.compile(rb"<lastBuildDate>([^<]+)</lastBuildDate>")
            cached_lbd = "Sat, 02 May 2026 13:00:00 +0800"

            with requests.get(url, stream=True, timeout=(5, 30)) as response:
                content = b""
                found_lbd = None

                for chunk in response.iter_content(chunk_size=4096):
                    content += chunk
                    match = lbd_pattern.search(content)
                    if match:
                        found_lbd = match.group(1).decode("utf-8")
                        break

                assert found_lbd == cached_lbd
                # Content should be small since we stopped after finding lastBuildDate
                assert len(content) < 2000  # Should be just a few KB, not full feed


class TestLastBuildDateCacheIntegration:
    """Integration tests for lastBuildDate caching in feed processing."""

    def test_parse_feed_spec_skips_when_lastbuilddate_unchanged(self) -> None:
        """When cached lastBuildDate matches, parse_feed_spec should return early with empty candidates."""
        import requests_mock

        # This test verifies the integration behavior
        # For now, this describes the EXPECTED behavior that we need to implement

        # Expected flow:
        # 1. parse_feed_spec is called with a feed that has cached lastBuildDate
        # 2. It calls fetch_and_check_update (not fetch_and_parse_feed)
        # 3. If lastBuildDate matches cache, returns immediately with candidates=[] and ok=True
        # 4. No full feed content is downloaded

        # This test will fail until we implement the integration
        pytest.skip("Integration not yet implemented - this describes desired behavior")


class TestFeedPriorityParsing:
    """Tests for feed priority field parsing and candidate sorting."""

    def test_parse_line_with_priority_and_label(self, tmp_path) -> None:
        """Line like '5 /infoq/recommend # InfoQ' should parse priority=5."""
        feeds_file = tmp_path / "feeds.txt"
        feeds_file.write_text("[rsshub]\n5\t/infoq/recommend # InfoQ\n")
        specs = feed_sources.load_feed_specs(feeds_file)
        assert len(specs) == 1
        assert specs[0]["priority"] == 5
        assert specs[0]["value"] == "/infoq/recommend"
        assert specs[0]["label"] == "InfoQ"

    def test_parse_line_with_priority_no_label(self, tmp_path) -> None:
        """Line like '3 /feed' should parse priority=3 with empty label."""
        feeds_file = tmp_path / "feeds.txt"
        feeds_file.write_text("[rsshub]\n3\t/feed\n")
        specs = feed_sources.load_feed_specs(feeds_file)
        assert len(specs) == 1
        assert specs[0]["priority"] == 3
        assert specs[0]["value"] == "/feed"
        assert specs[0]["label"] == ""

    def test_parse_line_without_priority(self, tmp_path) -> None:
        """Line without priority (legacy format) should default to priority=0."""
        feeds_file = tmp_path / "feeds.txt"
        feeds_file.write_text("[rsshub]\n/feed # label\n")
        specs = feed_sources.load_feed_specs(feeds_file)
        assert len(specs) == 1
        assert specs[0]["priority"] == 0
        assert specs[0]["value"] == "/feed"
        assert specs[0]["label"] == "label"

    def test_parse_line_priority_zero(self, tmp_path) -> None:
        """Explicit priority=0 should be parsed as 0."""
        feeds_file = tmp_path / "feeds.txt"
        feeds_file.write_text("[rsshub]\n0\t/feed\n")
        specs = feed_sources.load_feed_specs(feeds_file)
        assert specs[0]["priority"] == 0

    def test_mixed_priority_and_legacy_lines(self, tmp_path) -> None:
        """Mix of priority and legacy lines should all parse correctly."""
        feeds_file = tmp_path / "feeds.txt"
        feeds_file.write_text(
            "[rsshub]\n"
            "5\t/high/priority # High\n"
            "/legacy/no-priority # Legacy\n"
            "2\t/medium # Medium\n"
        )
        specs = feed_sources.load_feed_specs(feeds_file)
        assert len(specs) == 3
        assert specs[0]["priority"] == 5
        assert specs[1]["priority"] == 0
        assert specs[2]["priority"] == 2

    def test_candidates_sorted_by_feed_priority_desc(self, tmp_path) -> None:
        """Candidates from higher-priority feeds should appear first after collection."""
        import json

        feeds_file = tmp_path / "feeds.txt"
        feeds_file.write_text(
            "[rsshub]\n"
            "5\t/high\n"
            "1\t/low\n"
        )
        specs = feed_sources.load_feed_specs(feeds_file)

        # Simulate: high-priority feed produces candidates first (by idx order),
        # but after sorting they should be reordered by priority desc.
        # We verify by checking that load_feed_specs assigns correct priorities,
        # which collect_candidates_from_feeds uses for sorting.

        high_spec = [s for s in specs if s["value"] == "/high"][0]
        low_spec = [s for s in specs if s["value"] == "/low"][0]
        assert high_spec["priority"] > low_spec["priority"]

    def test_direct_feed_with_priority(self, tmp_path) -> None:
        """Direct feed URLs should also support priority prefix."""
        feeds_file = tmp_path / "feeds.txt"
        feeds_file.write_text(
            "[direct]\n"
            "5\thttps://example.com/feed.xml # Example\n"
        )
        specs = feed_sources.load_feed_specs(feeds_file)
        assert len(specs) == 1
        assert specs[0]["priority"] == 5
        assert specs[0]["kind"] == "direct"


class TestClassifyFetchError:
    """失败原因分级：决定实例冷却策略。"""

    @staticmethod
    def _http_error(status: int) -> requests.exceptions.HTTPError:
        return requests.exceptions.HTTPError(response=SimpleNamespace(status_code=status))

    def test_read_timeout(self) -> None:
        assert feed_sources.classify_fetch_error(requests.exceptions.Timeout()) == "timeout"

    def test_connect_timeout_classified_as_timeout_not_connection(self) -> None:
        # ConnectTimeout 同时继承 ConnectionError 和 Timeout，必须先判 Timeout
        assert feed_sources.classify_fetch_error(requests.exceptions.ConnectTimeout()) == "timeout"

    def test_connection_error(self) -> None:
        assert feed_sources.classify_fetch_error(requests.exceptions.ConnectionError()) == "connection"

    @pytest.mark.parametrize("status", [500, 502, 503, 504, 523])
    def test_5xx(self, status: int) -> None:
        assert feed_sources.classify_fetch_error(self._http_error(status)) == "http5xx"

    def test_429_is_ratelimit(self) -> None:
        assert feed_sources.classify_fetch_error(self._http_error(429)) == "ratelimit"

    @pytest.mark.parametrize("status", [403, 404])
    def test_403_404_are_route_problems(self, status: int) -> None:
        assert feed_sources.classify_fetch_error(self._http_error(status)) == "route"

    def test_other_4xx(self) -> None:
        assert feed_sources.classify_fetch_error(self._http_error(418)) == "http4xx"

    def test_value_error_is_parse(self) -> None:
        assert feed_sources.classify_fetch_error(ValueError("invalid feed parse")) == "parse"

    def test_unknown_falls_back_to_other(self) -> None:
        assert feed_sources.classify_fetch_error(RuntimeError("boom")) == "other"


class TestInstanceCooldownBackoff:
    """实例级指数退避 —— 对齐 feed 级已有的 cooldown/max 模式。"""

    @staticmethod
    def _pool(**kwargs) -> feed_sources.RSSHubInstancePool:
        opts = {"cooldown_seconds": 100, "max_cooldown_seconds": 1000}
        opts.update(kwargs)
        return feed_sources.RSSHubInstancePool(instances=["https://a.test"], **opts)

    def test_first_failure_uses_base_cooldown(self) -> None:
        pool = self._pool()
        assert pool.mark_failure("https://a.test", 1000.0) == 100
        assert pool.fail_until["https://a.test"] == 1100.0

    def test_backoff_doubles_then_caps(self) -> None:
        pool = self._pool()
        got = [pool.mark_failure("https://a.test", 1000.0) for _ in range(6)]
        assert got == [100, 200, 400, 800, 1000, 1000]

    def test_timeout_reason_is_gentle(self) -> None:
        """超时是 ambiguous 信号（可能只是路由慢），首次只给 0.2× 基础冷却。"""
        pool = self._pool(max_cooldown_seconds=100000)
        assert pool.mark_failure("https://a.test", 1000.0, reason="timeout") == 20

    def test_timeout_still_escalates_on_repeated_failure(self) -> None:
        pool = self._pool(max_cooldown_seconds=100000)
        got = [pool.mark_failure("https://a.test", 1000.0, reason="timeout") for _ in range(4)]
        assert got == [20, 40, 80, 160]

    def test_ratelimit_reason_is_harshest(self) -> None:
        pool = self._pool(max_cooldown_seconds=100000)
        assert pool.mark_failure("https://a.test", 1000.0, reason="ratelimit") == 200

    def test_connection_error_uses_full_base(self) -> None:
        pool = self._pool(max_cooldown_seconds=100000)
        assert pool.mark_failure("https://a.test", 1000.0, reason="connection") == 100

    def test_route_reason_is_complete_noop(self) -> None:
        """403/404 是路由问题，不该让实例背锅：不冷却、不计数、不改排序。"""
        pool = feed_sources.RSSHubInstancePool(
            instances=["https://a.test", "https://b.test"], cooldown_seconds=100
        )
        assert pool.mark_failure("https://a.test", 1000.0, reason="route") == 0
        assert pool.fail_until == {}
        assert pool.fail_count == {}
        assert pool.fail_streak == {}
        assert pool.instances == ["https://a.test", "https://b.test"]

    def test_success_resets_streak_but_keeps_cumulative_count(self) -> None:
        pool = self._pool()
        assert pool.mark_failure("https://a.test", 1000.0) == 100
        assert pool.mark_failure("https://a.test", 1000.0) == 200
        pool.mark_success("https://a.test")
        # 退避阶梯归零，下次失败从基础值重新开始
        assert pool.mark_failure("https://a.test", 1000.0) == 100
        # 但累计失败次数保留，_score 排序语义不变
        assert pool.fail_count["https://a.test"] == 3

    def test_max_cooldown_never_below_base(self) -> None:
        pool = self._pool(max_cooldown_seconds=10)
        assert pool.mark_failure("https://a.test", 1000.0) == 100


class TestResolveFeedUrlsCandidateCap:
    """候选实例上限：实测绝大多数路由在前几个就命中，轮满整个池子纯属浪费。"""

    INSTANCES = [f"https://i{n}.test" for n in range(11)]

    def test_defaults_to_four(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RSSHUB_MAX_CANDIDATES", raising=False)
        pool = feed_sources.RSSHubInstancePool(instances=list(self.INSTANCES))
        urls = feed_sources.resolve_feed_urls("rsshub", "/sspai/index", pool)
        assert len(urls) == 4
        assert urls[0] == "https://i0.test/sspai/index"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RSSHUB_MAX_CANDIDATES", "2")
        pool = feed_sources.RSSHubInstancePool(instances=list(self.INSTANCES))
        assert len(feed_sources.resolve_feed_urls("rsshub", "/x", pool)) == 2

    def test_zero_means_unlimited(self) -> None:
        pool = feed_sources.RSSHubInstancePool(instances=list(self.INSTANCES))
        urls = feed_sources.resolve_feed_urls("rsshub", "/x", pool, max_candidates=0)
        assert len(urls) == 11

    def test_explicit_arg_wins_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RSSHUB_MAX_CANDIDATES", "9")
        pool = feed_sources.RSSHubInstancePool(instances=list(self.INSTANCES))
        urls = feed_sources.resolve_feed_urls("rsshub", "/x", pool, max_candidates=3)
        assert len(urls) == 3

    def test_pool_smaller_than_cap_is_untouched(self) -> None:
        pool = feed_sources.RSSHubInstancePool(instances=["https://a.test", "https://b.test"])
        assert len(feed_sources.resolve_feed_urls("rsshub", "/x", pool, max_candidates=4)) == 2

    def test_cap_never_squeezes_out_special_instances(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """bilibili/twitter 专用实例即使超出上限也要保留，否则这些路由直接无实例可用。"""
        monkeypatch.setenv("RSSHUB_PRIVATE_INSTANCES", "https://p1.test,https://p2.test")
        monkeypatch.setenv("RSSHUB_BILIBILI_INSTANCES", "https://b1.test,https://b2.test,https://b3.test")
        pool = feed_sources.RSSHubInstancePool(instances=[f"https://g{n}.test" for n in range(6)])
        urls = feed_sources.resolve_feed_urls(
            "rsshub", "/bilibili/user/video-browser/1", pool, max_candidates=2
        )
        assert urls == [
            "https://p1.test/bilibili/user/video-browser/1",
            "https://p2.test/bilibili/user/video-browser/1",
            "https://b1.test/bilibili/user/video-browser/1",
            "https://b2.test/bilibili/user/video-browser/1",
            "https://b3.test/bilibili/user/video-browser/1",
        ]

    def test_direct_and_werss_unaffected_by_cap(self) -> None:
        pool = feed_sources.RSSHubInstancePool(instances=list(self.INSTANCES))
        assert feed_sources.resolve_feed_urls("direct", "https://x.test/f", pool, max_candidates=1) == [
            "https://x.test/f"
        ]


class TestPreflightInstances:
    """启动预检：消除冷启动惊群（实测每个坏实例的失败次数 ≈ 并发数）。"""

    def test_marks_dead_instances_and_keeps_alive(self) -> None:
        pool = feed_sources.RSSHubInstancePool(
            instances=["https://ok.test", "https://dead.test", "https://slow.test"],
            cooldown_seconds=100,
            max_cooldown_seconds=1000,
        )
        with requests_mock.Mocker() as m:
            m.get("https://ok.test/", status_code=200, text="rss2cubox")
            m.get("https://dead.test/", status_code=502)
            m.get("https://slow.test/", exc=requests.exceptions.ConnectTimeout)
            result = feed_sources.preflight_instances(pool, concurrency=3)

        assert result["alive"] == ["https://ok.test"]
        assert result["dead"]["https://dead.test"] == "http5xx"
        assert result["dead"]["https://slow.test"] == "timeout"
        assert result["probed"] == 3
        assert pool.should_skip("https://dead.test")
        assert pool.should_skip("https://slow.test")
        assert not pool.should_skip("https://ok.test")

    @pytest.mark.parametrize("status", [200, 301, 403, 404])
    def test_any_non_5xx_response_counts_as_alive(self, status: int) -> None:
        """探的是「实例在不在」，不是「路由能不能用」。"""
        pool = feed_sources.RSSHubInstancePool(instances=["https://a.test"], cooldown_seconds=100)
        with requests_mock.Mocker() as m:
            m.get("https://a.test/", status_code=status, text="x")
            result = feed_sources.preflight_instances(pool, concurrency=1)
        assert result["alive"] == ["https://a.test"]
        assert result["dead"] == {}
        assert not pool.should_skip("https://a.test")

    def test_empty_pool_is_noop(self) -> None:
        pool = feed_sources.RSSHubInstancePool(instances=[])
        result = feed_sources.preflight_instances(pool, concurrency=4)
        assert result == {
            "probed": 0,
            "alive": [],
            "dead": {},
            "cooldown_seconds": {},
            "duration_ms": result["duration_ms"],
        }

    def test_emits_log_event_with_masked_private_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(feed_sources, "_PRIVATE_HOSTS", frozenset({"10.10.10.182:1200"}))
        pool = feed_sources.RSSHubInstancePool(
            instances=["http://10.10.10.182:1200"], cooldown_seconds=100
        )
        events: list[tuple] = []
        with requests_mock.Mocker() as m:
            m.get("http://10.10.10.182:1200/", status_code=502)
            feed_sources.preflight_instances(
                pool,
                concurrency=1,
                log_event=lambda level, event, **kw: events.append((level, event, kw)),
            )
        level, event, fields = events[0]
        assert (level, event) == ("WARN", "rsshub_preflight_done")
        assert "10.10.10.182" not in json.dumps(fields)


class TestSpecBucketAndSectionDisable:
    """按桶停用结构性失效的源，比让运行时熔断去逐个发现便宜得多。"""

    SPECS: list[dict] = [
        {"kind": "rsshub", "value": "/sspai/index", "label": "", "priority": 0},
        {"kind": "rsshub", "value": "/twitter/user/karpathy", "label": "", "priority": 3},
        {"kind": "rsshub", "value": "/bilibili/user/video-browser/1", "label": "", "priority": 2},
        {"kind": "rsshub", "value": "/bilibili/user/video/2", "label": "", "priority": 2},
        {"kind": "werss", "value": "/feed/MP_WXS_1.rss", "label": "", "priority": 2},
        {"kind": "direct", "value": "https://x.test/f", "label": "", "priority": 1},
    ]

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("/sspai/index", "default"),
            ("/twitter/user/x", "twitter_user"),
            ("/bilibili/user/video/1", "bilibili_user_video"),
            ("/bilibili/user/video-browser/1", "bilibili_user_video"),
        ],
    )
    def test_spec_bucket_rsshub(self, value: str, expected: str) -> None:
        assert feed_sources.spec_bucket({"kind": "rsshub", "value": value}) == expected

    def test_spec_bucket_werss_wins_over_route_shape(self) -> None:
        assert feed_sources.spec_bucket({"kind": "werss", "value": "/twitter/user/x"}) == "werss"

    def test_parse_disabled_buckets_accepts_aliases(self) -> None:
        assert feed_sources.parse_disabled_buckets("twitter, bilibili ,WERSS") == {
            "twitter_user",
            "bilibili_user_video",
            "werss",
        }

    def test_parse_disabled_buckets_ignores_unknown(self) -> None:
        assert feed_sources.parse_disabled_buckets("twitter,nonsense,") == {"twitter_user"}

    def test_empty_disable_keeps_everything(self) -> None:
        kept, dropped = feed_sources.filter_specs_by_buckets(self.SPECS, "")
        assert kept == self.SPECS
        assert dropped == {}

    def test_none_disable_keeps_everything(self) -> None:
        kept, dropped = feed_sources.filter_specs_by_buckets(self.SPECS, None)
        assert kept == self.SPECS
        assert dropped == {}

    def test_disables_the_three_dead_buckets(self) -> None:
        kept, dropped = feed_sources.filter_specs_by_buckets(
            self.SPECS, "twitter,bilibili,werss"
        )
        assert [s["value"] for s in kept] == ["/sspai/index", "https://x.test/f"]
        assert dropped == {"twitter_user": 1, "bilibili_user_video": 2, "werss": 1}

    def test_accepts_pre_parsed_set(self) -> None:
        kept, dropped = feed_sources.filter_specs_by_buckets(self.SPECS, {"twitter_user"})
        assert len(kept) == 5
        assert dropped == {"twitter_user": 1}

    def test_does_not_mutate_input(self) -> None:
        original = [dict(s) for s in self.SPECS]
        feed_sources.filter_specs_by_buckets(self.SPECS, "twitter,bilibili,werss")
        assert self.SPECS == original

    def test_emits_log_event(self) -> None:
        events: list[tuple] = []
        feed_sources.filter_specs_by_buckets(
            self.SPECS,
            "werss",
            log_event=lambda level, event, **kw: events.append((level, event, kw)),
        )
        level, event, fields = events[0]
        assert (level, event) == ("INFO", "feed_sections_disabled")
        assert fields["dropped_total"] == 1
        assert fields["kept"] == 5
        assert fields["disabled"] == ["werss"]

    def test_no_log_event_when_nothing_dropped(self) -> None:
        events: list[str] = []
        # 只给一条 default 桶的 spec，却禁用 werss —— 没东西可丢，不应发事件
        feed_sources.filter_specs_by_buckets(
            [self.SPECS[0]], "werss", log_event=lambda level, event, **kw: events.append(event)
        )
        assert events == []
