"""fulltext_fetcher 三级降级全文抓取 — 单元测试"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from rss2cubox.fulltext_fetcher import FetchResult


# ── 测试 L1 trafilatura ────────────────────────────────
class TestL1Trafilatura:
    def test_l1_success(self):
        with patch("rss2cubox.fulltext_fetcher._l1_download") as mock_dl, \
             patch("trafilatura.extract") as mock_ex:
            mock_dl.return_value = "<html><article><p>Hello World</p></article>"
            mock_ex.return_value = "Hello World " * 10  # ≥ 80 chars
            from rss2cubox.fulltext_fetcher import _fetch_l1_trafilatura

            result = _fetch_l1_trafilatura("https://example.com/article")
            assert result is not None
            assert result.text == ("Hello World " * 10).strip()
            assert result.source == "trafilatura"
            assert result.level == 1

    def test_l1_falls_back_to_trafilatura_fetcher(self):
        """requests 下载失败时要回退到 trafilatura 自己的下载器。"""
        with patch("rss2cubox.fulltext_fetcher._l1_download", return_value=""), \
             patch("trafilatura.fetch_url", return_value="<html>fb</html>") as mock_fb, \
             patch("trafilatura.extract", return_value="y" * 100):
            from rss2cubox.fulltext_fetcher import _fetch_l1_trafilatura

            result = _fetch_l1_trafilatura("https://example.com/x")
            mock_fb.assert_called_once()
            assert result.text == "y" * 100

    def test_l1_download_empty_returns_error_result(self):
        with patch("rss2cubox.fulltext_fetcher._l1_download", return_value=""), \
             patch("trafilatura.fetch_url", return_value=""):
            from rss2cubox.fulltext_fetcher import _fetch_l1_trafilatura

            result = _fetch_l1_trafilatura("https://example.com/empty")
            assert result is not None and result.text == ""
            assert result.error == "l1_download_failed"

    def test_l1_extract_too_short_reports_length(self):
        with patch("rss2cubox.fulltext_fetcher._l1_download", return_value="<html>short</html>"), \
             patch("trafilatura.extract", return_value="x" * 30):
            from rss2cubox.fulltext_fetcher import _fetch_l1_trafilatura

            result = _fetch_l1_trafilatura("https://example.com/short")
            assert result.text == ""
            assert result.error == "l1_text_too_short:30"

    def test_l1_exception_reports_type(self):
        with patch("rss2cubox.fulltext_fetcher._l1_download", side_effect=RuntimeError("boom")):
            from rss2cubox.fulltext_fetcher import _fetch_l1_trafilatura

            result = _fetch_l1_trafilatura("https://example.com/error")
            assert result.text == ""
            assert "RuntimeError" in result.error and "boom" in result.error


class TestL1UsesProxyAwareDownloader:
    """回归：trafilatura.fetch_url 不读代理环境变量，必须自己用 requests 下载。

    实测背景：本机访问境外站点必须走本地代理（huggingface.co 走代理 200/1.7s，
    直连 20s 超时）。trafilatura.fetch_url 基于 urllib3.PoolManager，不读
    HTTP(S)_PROXY，所以会直连并挂到 30s 失败。这一个差别导致一次完整运行里
    全文抓取 0/368 全部失败，而隔离测试（恰好命中不需要代理的站点）看起来正常。
    """

    def test_download_uses_requests_not_trafilatura_fetcher(self):
        from rss2cubox.fulltext_fetcher import _l1_download

        with patch("requests.get") as mock_get, \
             patch("trafilatura.fetch_url") as mock_tf:
            mock_get.return_value = MagicMock(
                status_code=200, text="<html>ok</html>", encoding="utf-8",
                raise_for_status=lambda: None,
            )
            assert _l1_download("https://example.com/a") == "<html>ok</html>"
            mock_get.assert_called_once()
            mock_tf.assert_not_called()   # 不能走 trafilatura 的直连下载器

    def test_download_returns_empty_on_http_error(self):
        from rss2cubox.fulltext_fetcher import _l1_download

        with patch("requests.get") as mock_get:
            def boom():
                raise RuntimeError("403 Client Error")
            mock_get.return_value = MagicMock(raise_for_status=boom)
            assert _l1_download("https://example.com/blocked") == ""

    def test_download_returns_empty_on_network_error(self):
        from rss2cubox.fulltext_fetcher import _l1_download

        with patch("requests.get", side_effect=OSError("unreachable")):
            assert _l1_download("https://example.com/x") == ""

    def test_download_fixes_missing_charset(self):
        """未声明 charset 时 requests 默认 ISO-8859-1，中文站会乱码。"""
        from rss2cubox.fulltext_fetcher import _l1_download

        resp = MagicMock(status_code=200, encoding="ISO-8859-1",
                         apparent_encoding="gb2312", raise_for_status=lambda: None)
        resp.text = "政策"
        with patch("requests.get", return_value=resp):
            _l1_download("https://example.gov.cn/x")
        assert resp.encoding == "gb2312"

    def test_download_timeout_leaves_margin_for_outer_budget(self):
        """下载超时必须小于外层 L1 预算，否则又是“内部≈外层”的老坑。"""
        import inspect
        from rss2cubox import fulltext_fetcher as mod

        src = inspect.getsource(mod._l1_download)
        assert "_L1_TIMEOUT_S - 1" in src


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
            assert result.error.startswith("all_levels_failed")

    def test_error_distinguishes_no_content_from_timeout(self):
        """回归：原来超时、抛异常、跑完但无正文全部报成 None，
        最后只剩一个笼统的 all_levels_failed，无法判断该调超时还是该换抽取方式。"""
        with patch("rss2cubox.fulltext_fetcher._fetch_l1_trafilatura") as mock_l1, \
             patch("rss2cubox.fulltext_fetcher._fetch_l2_playwright") as mock_l2, \
             patch("rss2cubox.fulltext_fetcher._is_wechat_url") as mock_wc:
            mock_l1.return_value = None
            mock_l2.return_value = None
            mock_wc.return_value = False

            from rss2cubox.fulltext_fetcher import fetch_full_text

            err = fetch_full_text("https://fail.example.com").error
            assert "l1=no_content" in err
            assert "l2=no_content" in err

    def test_error_reports_l2_timeout_explicitly(self):
        """L2 超时必须能看出来 —— 这正是并发过高时的真实形态。"""
        import time as _time

        def slow(_url):  # noqa: ANN001
            _time.sleep(3)
            return None

        with patch("rss2cubox.fulltext_fetcher._fetch_l1_trafilatura", return_value=None), \
             patch("rss2cubox.fulltext_fetcher._fetch_l2_playwright", side_effect=slow), \
             patch("rss2cubox.fulltext_fetcher._is_wechat_url", return_value=False), \
             patch("rss2cubox.fulltext_fetcher._L2_TIMEOUT_S", 0.5):
            from rss2cubox.fulltext_fetcher import fetch_full_text

            err = fetch_full_text("https://slow.example.com").error
            assert "l2=timeout>" in err

    def test_error_propagates_exception_type(self):
        with patch("rss2cubox.fulltext_fetcher._fetch_l1_trafilatura",
                   side_effect=RuntimeError("boom")), \
             patch("rss2cubox.fulltext_fetcher._fetch_l2_playwright", return_value=None), \
             patch("rss2cubox.fulltext_fetcher._is_wechat_url", return_value=False):
            from rss2cubox.fulltext_fetcher import fetch_full_text

            err = fetch_full_text("https://err.example.com").error
            assert "l1=RuntimeError" in err and "boom" in err

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


class TestLevelBudgetInvariant:
    """L2 的内部预算必须显著小于它的外层预算。

    回归背景：默认配置下 nav=15 + launch~2 + render_wait=2 ≈ 19s，而外层
    _L2_TIMEOUT_S = min(20, T//2) 硬封顶 20s（把 FULLTEXT_ITEM_TIMEOUT_S 调多大
    都没用），余量为零。只要有一点并发争抢，外层就会在 playwright 完成前砍掉它，
    且被丢弃的子线程继续持有浏览器。实测一次完整运行 22 次全文尝试 0 成功，
    而隔离测试同样的 URL 有 60% 成功率。
    """

    def test_playwright_inner_budget_fits_in_outer(self) -> None:
        from rss2cubox import fulltext_fetcher as mod

        # launch 开销按 2s 估
        inner = 2 + mod._PLAYWRIGHT_NAVIGATION_TIMEOUT_S + mod._RENDER_EXTRA_WAIT_S
        assert inner < mod._L2_TIMEOUT_S, (
            f"L2 内部预算 {inner}s 必须小于外层 {mod._L2_TIMEOUT_S}s，"
            f"否则外层超时会在 playwright 完成前砍掉它"
        )

    def test_inner_budget_keeps_at_least_25pct_margin(self) -> None:
        from rss2cubox import fulltext_fetcher as mod

        inner = 2 + mod._PLAYWRIGHT_NAVIGATION_TIMEOUT_S + mod._RENDER_EXTRA_WAIT_S
        margin = (mod._L2_TIMEOUT_S - inner) / mod._L2_TIMEOUT_S
        assert margin >= 0.25, f"L2 余量只有 {margin:.0%}，并发争抢下必然超时"

    def test_l2_outer_budget_is_hard_capped_at_20(self) -> None:
        """锁住这个反直觉的行为：调大 FULLTEXT_ITEM_TIMEOUT_S 并不能给 L2 更多时间。"""
        from rss2cubox import fulltext_fetcher as mod

        assert mod._L2_TIMEOUT_S <= 20

    @pytest.mark.parametrize("item_timeout", [30, 60, 90, 120])
    def test_invariant_holds_across_item_timeout_values(self, item_timeout: int) -> None:
        """无论 FULLTEXT_ITEM_TIMEOUT_S 设多少，钳制逻辑都要保住余量。"""
        l2 = min(20, item_timeout // 2)
        nav = max(4, min(15, int(l2 * 0.5)))
        wait = max(1, min(2, max(1, int(l2 * 0.1))))
        inner = 2 + nav + wait
        assert inner < l2, f"T={item_timeout} 时 L2 内部 {inner}s ≥ 外层 {l2}s"


class TestBatchLogEventSignature:
    """回归：log_event 的签名是 (level, event, **fields)，任何叫 level 的字段都会撞名。

    这个 bug 的实际后果很隐蔽：results[eid] 在 log_event 之前就赋值了，异常又在
    ThreadPoolExecutor 里被吞掉，所以全文其实抓成功了，但 fulltext_done 事件
    一条都记不出来 —— 日志上表现为"0 成功"，排查时被误导了很久。
    """

    @staticmethod
    def _runner_style_log_event(level: str, event: str, **fields):
        """与 runner.py / policy_runner.py / prediction_loop_runner.py 完全同签名。"""
        return (level, event, fields)

    def test_done_event_does_not_collide_with_level_param(self) -> None:
        from rss2cubox.fulltext_fetcher import fetch_fulltext_batch

        events = []
        with patch("rss2cubox.fulltext_fetcher.fetch_full_text") as mock_fetch:
            mock_fetch.return_value = FetchResult(text="x" * 200, source="trafilatura", level=1)
            fetch_fulltext_batch(
                [{"eid": "a1", "url": "https://e.com/1"}],
                max_workers=1,
                log_event=lambda *a, **k: events.append((a, k)),
            )

        names = [k.get("event") or (a[1] if len(a) > 1 else None) for a, k in events]
        assert "fulltext_done" in names, f"成功事件未记录，实际事件: {names}"
        done = next(k for a, k in events if (k.get("event") or (a[1] if len(a) > 1 else None)) == "fulltext_done")
        # 层级字段必须改名，不能占用 level
        assert done.get("fetch_level") == 1
        assert "level" not in done

    def test_real_runner_signature_accepts_both_events(self) -> None:
        """直接用 runner 的真实签名跑，成功和失败两条路径都不能抛 TypeError。"""
        from rss2cubox.fulltext_fetcher import fetch_fulltext_batch

        captured = []

        def log_event(level: str, event: str, **fields):
            captured.append((level, event))

        def fake_fetch(url: str):
            if "bad" in url:
                return FetchResult(error="all_levels_failed: l1=no_content | l2=disabled")
            return FetchResult(text="y" * 200, source="trafilatura", level=1, elapsed_s=0.5)

        with patch("rss2cubox.fulltext_fetcher.fetch_full_text", side_effect=fake_fetch):
            result = fetch_fulltext_batch(
                [{"eid": "ok", "url": "https://e.com/ok"}, {"eid": "bad", "url": "https://e.com/bad"}],
                max_workers=2,
                log_event=log_event,
            )

        assert ("INFO", "fulltext_done") in captured
        assert ("WARN", "fulltext_failed") in captured
        assert len(result) == 1 and "ok" in result

    def test_no_log_event_kwarg_named_level_anywhere(self) -> None:
        """静态兜底：源码里不得再出现向 log_event 传 level= 的写法。"""
        import re
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent / "src" / "rss2cubox"
        offenders = []
        for path in src.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"log_event\(([^)]*)\)", text, re.S):
                body = match.group(1)
                if re.search(r"(?<![\w.])level\s*=", body):
                    offenders.append(f"{path.name}: {body.strip()[:60]}")
        assert not offenders, f"发现向 log_event 传 level= 的调用: {offenders}"
