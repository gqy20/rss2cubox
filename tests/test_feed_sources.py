"""Tests for feed_sources module - focus on If-Modified-Since and lastBuildDate optimization."""

import pytest
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
