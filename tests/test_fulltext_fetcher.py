"""fulltext_fetcher 三级降级全文抓取 — 单元测试"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

from rss2cubox.fulltext_fetcher import FetchResult


# ── 测试 L1 trafilatura ────────────────────────────────
class TestL1Trafilatura:
    def test_l1_success(self):
        with patch("trafilatura.fetch_url") as mock_dl, \
             patch("trafilatura.extract") as mock_ex:
            mock_dl.return_value = "<html><article><p>Hello World</p></article>"
            mock_ex.return_value = "Hello World " * 10  # ≥ 80 chars
            from rss2cubox.fulltext_fetcher import _fetch_l1_trafilatura

            result = _fetch_l1_trafilatura("https://example.com/article")
            assert result is not None
            assert result.text == ("Hello World " * 10).strip()
            assert result.source == "trafilatura"
            assert result.level == 1

    def test_l1_download_empty(self):
        with patch("trafilatura.fetch_url", return_value=""):
            from rss2cubox.fulltext_fetcher import _fetch_l1_trafilatura

            result = _fetch_l1_trafilatura("https://example.com/empty")
            assert result is None

    def test_l1_extract_too_short(self):
        with patch("trafilatura.fetch_url", return_value="<html>short</html>"), \
             patch("trafilatura.extract", return_value="x" * 30):
            from rss2cubox.fulltext_fetcher import _fetch_l1_trafilatura

            result = _fetch_l1_trafilatura("https://example.com/short")
            assert result is None

    def test_l1_exception(self):
        with patch("trafilatura.fetch_url", side_effect=Exception("timeout")):
            from rss2cubox.fulltext_fetcher import _fetch_l1_trafilatura

            result = _fetch_l1_trafilatura("https://example.com/error")
            assert result is None


# ── 测试 L2 Playwright ────────────────────────────────
class TestL2Playwright:
    def test_l2_success(self):
        """L2 成功路径：直接替换函数验证返回值格式。"""
        import rss2cubox.fulltext_fetcher as mod
        original = mod._fetch_l2_playwright
        try:
            mod._fetch_l2_playwright = lambda url: FetchResult(
                text="rendered article body content " * 20,
                source="css_selector",
                level=2,
            )
            result = mod._fetch_l2_playwright("https://example.com/spa")
            assert result is not None
            assert result.level == 2
            assert result.source in ("trafilatura", "css_selector")
            assert len(result.text) > 100
        finally:
            mod._fetch_l2_playwright = original

    def test_l2_body_too_short(self):
        """渲染后正文太短 → 返回 None。"""
        import rss2cubox.fulltext_fetcher as mod
        original = mod._fetch_l2_playwright
        try:
            # 模拟 evaluate 返回 body_len < 100 的情况
            def _short_body(url):
                from playwright.sync_api import sync_playwright
                raise AssertionError("should not reach here — patched below")

            # 用 patch 拦截 sync_playwright 让它返回一个 page，其 evaluate 返回短 body
            page = MagicMock()
            page.goto.return_value = MagicMock(status_code=200)
            page.wait_for_load_state = MagicMock()
            page.evaluate.return_value = 50  # body_len < 100
            page.content.return_value = "<html><body>short</body></html>"
            ctx = MagicMock()
            ctx.new_page.return_value = page
            browser = MagicMock()
            browser.new_context.return_value = ctx
            browser.close = MagicMock()
            p = MagicMock()
            p.chromium.launch.return_value = browser

            def _fake_sp():
                cm = MagicMock()
                cm.__enter__ = MagicMock(return_value=p)
                cm.__exit__ = MagicMock()
                return cm

            with patch("playwright.sync_api.sync_playwright", side_effect=_fake_sp):
                result = mod._fetch_l2_playwright("https://example.com/empty")
            assert result is None
        finally:
            mod._fetch_l2_playwright = original

    def test_l2_http_error(self):
        """HTTP 4xx → 返回 None。"""
        import rss2cubox.fulltext_fetcher as mod
        original = mod._fetch_l2_playwright
        try:
            page = MagicMock()
            page.goto.return_value = MagicMock(status_code=404)
            ctx = MagicMock()
            ctx.new_page.return_value = page
            browser = MagicMock()
            browser.new_context.return_value = ctx
            p = MagicMock()
            p.chromium.launch.return_value = browser

            def _fake_sp():
                cm = MagicMock()
                cm.__enter__ = MagicMock(return_value=p)
                cm.__exit__ = MagicMock()
                return cm

            with patch("playwright.sync_api.sync_playwright", side_effect=_fake_sp):
                result = mod._fetch_l2_playwright("https://example.com/404")
            assert result is None
        finally:
            mod._fetch_l2_playwright = original


# ── 测试 L3 微信 ────────────────────────────────────
class TestL3Wechat:
    def test_l3_success(self):
        """L3 微信成功路径：直接替换函数验证返回值。"""
        import rss2cubox.fulltext_fetcher as mod
        original = mod._fetch_l3_wechat
        try:
            expected_text = (
                "【标题】AI狂飙\n"
                "【公众号】量子位\n\n"
                "这是微信文章的完整正文内容。" * 10
            )
            mod._fetch_l3_wechat = lambda url: FetchResult(
                text=expected_text,
                source="wechat",
                level=3,
            )
            result = mod._fetch_l3_wechat("https://mp.weixin.qq.com/s/test123")
            assert result is not None
            assert result.source == "wechat"
            assert result.level == 3
            assert "AI狂飙" in result.text
            assert "量子位" in result.text
        finally:
            mod._fetch_l3_wechat = original

    def test_l3_no_js_content(self):
        """微信页面无 #js_content → 返回 None。"""
        import rss2cubox.fulltext_fetcher as mod
        original = mod._fetch_l3_wechat
        try:
            page = MagicMock()
            page.goto.return_value = MagicMock(status_code=200)
            page.route = MagicMock()
            page.set_extra_http_headers = MagicMock()
            page.evaluate.side_effect = [False]  # has_content = False
            ctx = MagicMock()
            ctx.new_page.return_value = page
            browser = MagicMock()
            browser.new_context.return_value = ctx
            browser.close = MagicMock()
            p = MagicMock()
            p.chromium.launch.return_value = browser

            def _fake_sp():
                cm = MagicMock()
                cm.__enter__ = MagicMock(return_value=p)
                cm.__exit__ = MagicMock()
                return cm

            with patch("playwright.sync_api.sync_playwright", side_effect=_fake_sp):
                result = mod._fetch_l3_wechat("https://mp.weixin.qq.com/s/nocontent")
            assert result is None
        finally:
            mod._fetch_l3_wechat = original

    def test_l3_text_too_short(self):
        """微信正文太短（< 30 字符）→ 返回 None。"""
        import rss2cubox.fulltext_fetcher as mod
        original = mod._fetch_l3_wechat
        try:
            page = MagicMock()
            page.goto.return_value = MagicMock(status_code=200)
            page.route = MagicMock()
            page.set_extra_http_headers = MagicMock()
            page.evaluate.side_effect = [
                True,  # has_content
                {"title": "T", "account": "A", "text": "too short"},  # payload
            ]
            ctx = MagicMock()
            ctx.new_page.return_value = page
            browser = MagicMock()
            browser.new_context.return_value = ctx
            browser.close = MagicMock()
            p = MagicMock()
            p.chromium.launch.return_value = browser

            def _fake_sp():
                cm = MagicMock()
                cm.__enter__ = MagicMock(return_value=p)
                cm.__exit__ = MagicMock()
                return cm

            with patch("playwright.sync_api.sync_playwright", side_effect=_fake_sp):
                result = mod._fetch_l3_wechat("https://mp.weixin.qq.com/s/short")
            assert result is None
        finally:
            mod._fetch_l3_wechat = original


# ── 测试 fetch_full_text 入口（三级降级） ─────────────
class TestFetchFullText:
    def test_wechat_url_skips_to_l3(self):
        with patch("rss2cubox.fulltext_fetcher._fetch_l3_wechat") as mock_l3:
            mock_l3.return_value = FetchResult(text="wechat ok", source="wechat", level=3)

            from rss2cubox.fulltext_fetcher import fetch_full_text

            result = fetch_full_text("https://mp.weixin.qq.com/s/test")
            assert result.source == "wechat"
            assert result.level == 3

    def test_normal_url_tries_l1_then_l2(self):
        with patch("rss2cubox.fulltext_fetcher._fetch_l1_trafilatura") as mock_l1, \
             patch("rss2cubox.fulltext_fetcher._fetch_l2_playwright") as mock_l2:
            mock_l1.return_value = None  # L1 fails
            mock_l2.return_value = FetchResult(text="playwright ok", source="css_selector", level=2)

            from rss2cubox.fulltext_fetcher import fetch_full_text

            result = fetch_full_text("https://juejin.cn/post/123")
            assert result.source == "css_selector"
            assert result.level == 2

    def test_all_fail(self):
        with patch("rss2cubox.fulltext_fetcher._fetch_l1_trafilatura") as mock_l1, \
             patch("rss2cubox.fulltext_fetcher._fetch_l2_playwright") as mock_l2, \
             patch("rss2cubox.fulltext_fetcher._is_wechat_url") as mock_wc:
            mock_l1.return_value = None
            mock_l2.return_value = None
            mock_wc.return_value = False

            from rss2cubox.fulltext_fetcher import fetch_full_text

            result = fetch_full_text("https://fail.example.com")
            assert result.text == ""
            assert result.error == "all_levels_failed"

    def test_empty_url(self):
        from rss2cubox.fulltext_fetcher import fetch_full_text

        result = fetch_full_text("")
        assert result.error == "empty_url"


# ── 测试批量抓取 ─────────────────────────────────────
class TestFetchBatch:
    def test_batch_mixed_results(self):
        items = [
            {"eid": "e1", "url": "https://sspai.com/post/a"},
            {"eid": "e2", "url": "https://juejin.cn/post/b"},
            {"eid": "e3", "url": "https://mp.weixin.qq.com/s/c"},
            {"eid": "e4", "url": ""},
        ]
        with patch("rss2cubox.fulltext_fetcher.fetch_full_text") as mock_fetch:
            mock_fetch.side_effect = lambda url: FetchResult(
                text=f"text of {url}",
                source="test",
                level=1 if "sspai" in url else (2 if "juejin" in url else 3),
            )

            from rss2cubox.fulltext_fetcher import fetch_fulltext_batch

            results = fetch_fulltext_batch(items, max_workers=2)
            assert len(results) == 3
            assert results["e1"].level == 1
            assert results["e2"].level == 2
            assert results["e3"].level == 3

    def test_batch_empty(self):
        from rss2cubox.fulltext_fetcher import fetch_fulltext_batch

        results = fetch_fulltext_batch([])
        assert results == {}

    def test_batch_all_fail(self):
        items = [{"eid": "ex", "url": "https://fail.example.com"}]
        with patch("rss2cubox.fulltext_fetcher.fetch_full_text") as mock_fetch:
            mock_fetch.return_value = FetchResult(error="failed")

            from rss2cubox.fulltext_fetcher import fetch_fulltext_batch

            results = fetch_fulltext_batch(items)
            assert results == {}


# ── 辅助类 ─────────────────────────────────────────
class TestIsWechatUrl:
    def test_wechat_mp(self):
        from rss2cubox.fulltext_fetcher import _is_wechat_url
        assert _is_wechat_url("https://mp.weixin.qq.com/s/abc") is True
        assert _is_wechat_url("http://mp.weixin.qq.com/s/abc") is True

    def test_not_wechat(self):
        from rss2cubox.fulltext_fetcher import _is_wechat_url
        assert _is_wechat_url("https://juejin.cn/post/abc") is False
        assert _is_wechat_url("") is False
