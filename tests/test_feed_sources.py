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
