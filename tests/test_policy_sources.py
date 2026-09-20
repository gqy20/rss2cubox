"""政策信源子系统的单元测试（config + engine，不碰网络和数据库）。"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import requests
import requests_mock

from rss2cubox.policy import config as policy_config
from rss2cubox.policy import engine
from rss2cubox.policy.engine import PolicyItem


# ── 真实站点结构的 HTML 片段（2026-09-15 从线上页面扒下来的形状）──────────

BEIJING_HTML = """
<html><body><ul class="default_news">
  <li><i class="flag">是</i>
      <a href="./202609/t20260915_4864925.html" target="_blank"
         title="北京市文物局关于开展文博特色视频课程征集工作的通知">北京市文物局关于开展文博特色视频课程征集工作的通知</a>
      <span>2026-09-15</span></li>
  <li><i class="flag">是</i>
      <a href="./202609/t20260914_4862425.html" title="北京市人民政府关于试鸣防空警报的通告">北京市人民政府关于试鸣防空警报的通告</a>
      <span>2026-09-14</span></li>
  <li><a href="javascript:void(0)">更多</a><span>2026-09-13</span></li>
</ul></body></html>
"""

TC260_HTML = """
<html><body><ul class="inList">
  <li><a href="/tc260/xwdt1/202609/e879077a.shtml" title="《人工智能安全治理框架3.0》">
        <span class="date">2026-09-14</span>《人工智能安全治理框架3.0》</a></li>
  <li><a href="/tc260/tzgg/202609/4a537d5c.shtml" title="关于发布《座舱数据处理安全要求》的通知">
        <span class="date">2026年9月15日</span>关于发布《座舱数据处理安全要求》的通知</a></li>
</ul></body></html>
"""

GUANGDONG_HTML = """
<html><body><div class="viewList"><ul>
  <li><span class="name"><a href="https://www.gd.gov.cn/zwgk/wjk/qbwj/post_1.html">
        广东省人民政府关于湛江市历史文化名镇保护规划的批复</a></span>
      <span class="time">2026-09-15</span></li>
</ul></div></body></html>
"""


def _site(**overrides) -> policy_config.SiteSpec:
    base = dict(
        key="test_site",
        name="测试站点",
        level="province",
        region="测试",
        list_url="https://www.beijing.gov.cn/zhengce/zhengcefagui/",
        item_selector="ul.default_news > li",
    )
    base.update(overrides)
    return policy_config.parse_site(base)


# ══════════════════════════════════════════════════════════
class TestParsePolicyDate:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2026-09-15", "2026-09-15"),
            ("2026/09/15", "2026-09-15"),
            ("2026.09.15", "2026-09-15"),
            ("2026年9月15日", "2026-09-15"),
            ("2026年9月5日", "2026-09-05"),
            ("发布时间：2026-09-15 来源：北京市", "2026-09-15"),
        ],
    )
    def test_supported_formats(self, raw: str, expected: str) -> None:
        dt, matched = engine.parse_policy_date(raw)
        assert dt is not None
        assert dt.strftime("%Y-%m-%d") == expected
        assert matched

    def test_returns_none_when_no_date(self) -> None:
        assert engine.parse_policy_date("无日期文本") == (None, "")

    def test_invalid_day_returns_none_but_keeps_match(self) -> None:
        dt, matched = engine.parse_policy_date("2026-02-31")
        assert dt is None
        assert matched == "2026-02-31"

    def test_parsed_datetime_is_tz_aware(self) -> None:
        dt, _ = engine.parse_policy_date("2026-09-15")
        assert dt is not None and dt.tzinfo is not None


# ══════════════════════════════════════════════════════════
class TestStablePolicyId:
    def test_deterministic(self) -> None:
        assert engine.stable_policy_id("https://a.gov.cn/x.html") == engine.stable_policy_id(
            "https://a.gov.cn/x.html"
        )

    def test_strips_tracking_params(self) -> None:
        """与 sync_pipeline.stable_id 同约定：归一化后同一文档应得到同一 ID。"""
        assert engine.stable_policy_id("https://a.gov.cn/x.html?utm_source=rss") == engine.stable_policy_id(
            "https://a.gov.cn/x.html"
        )

    def test_different_urls_differ(self) -> None:
        assert engine.stable_policy_id("https://a.gov.cn/x.html") != engine.stable_policy_id(
            "https://a.gov.cn/y.html"
        )

    def test_length_is_sha256_hex(self) -> None:
        assert len(engine.stable_policy_id("https://a.gov.cn/x")) == 64


# ══════════════════════════════════════════════════════════
class TestParseListHtml:
    def test_beijing_relative_urls_are_resolved(self) -> None:
        site = _site()
        items, raw = engine.parse_list_html(BEIJING_HTML, site)
        assert raw == 3
        assert len(items) == 2  # 第三条 href=javascript: 被丢弃
        assert items[0].url == "https://www.beijing.gov.cn/zhengce/zhengcefagui/202609/t20260915_4864925.html"
        assert items[0].title == "北京市文物局关于开展文博特色视频课程征集工作的通知"
        assert items[0].published_at.strftime("%Y-%m-%d") == "2026-09-15"

    def test_title_prefers_attr_over_text(self) -> None:
        items, _ = engine.parse_list_html(TC260_HTML, _tc260_site(title_attr="title"))
        assert items[0].title == "《人工智能安全治理框架3.0》"
        # a 的可见文本里还含日期，所以取 attr 才是干净标题
        assert "2026-09-14" not in items[0].title

    def test_falls_back_to_text_when_attr_missing(self) -> None:
        site = _tc260_site(title_attr="data-nonexistent")
        items, _ = engine.parse_list_html(TC260_HTML, site)
        # 回退到 a 的文本，里面含日期，但仍应保留标题部分
        assert "人工智能安全治理框架3.0" in items[0].title

    def test_nested_title_selector(self) -> None:
        """广东站标题在 span.name > a 里，不是 li 直接子元素。"""
        site = _site(
            item_selector="div.viewList > ul > li",
            title_selector="span.name > a",
            url_selector="span.name > a",
            list_url="https://www.gd.gov.cn/zwgk/wjk/qbwj/",
        )
        items, _ = engine.parse_list_html(GUANGDONG_HTML, site)
        assert len(items) == 1
        assert items[0].title == "广东省人民政府关于湛江市历史文化名镇保护规划的批复"
        assert items[0].url.endswith("post_1.html")

    def test_date_selector_then_regex_fallback(self) -> None:
        """TC260 第二条日期是「2026年9月15日」，date_selector 命中 span.date。"""
        items, _ = engine.parse_list_html(TC260_HTML, _tc260_site())
        assert items[1].published_at.strftime("%Y-%m-%d") == "2026-09-15"
        # 去掉 date_selector 后应从整项文本里正则兜底
        items2, _ = engine.parse_list_html(TC260_HTML, _tc260_site(date_selector=""))
        assert items2[1].published_at.strftime("%Y-%m-%d") == "2026-09-15"

    def test_relative_url_uses_base_url_override(self) -> None:
        site = _site(base_url="https://mirror.example.cn/policy/")
        items, _ = engine.parse_list_html(BEIJING_HTML, site)
        assert items[0].url.startswith("https://mirror.example.cn/policy/202609/")

    def test_max_items_caps_output(self) -> None:
        items, raw = engine.parse_list_html(BEIJING_HTML, _site(max_items=1))
        assert raw == 3
        assert len(items) == 1

    def test_min_title_length_filters_nav_links(self) -> None:
        html = """<ul class="l"><li><a href="/a" title="短">短</a><span>2026-09-15</span></li>
                  <li><a href="/b" title="这是一个足够长的政策标题">这是一个足够长的政策标题</a><span>2026-09-15</span></li></ul>"""
        items, raw = engine.parse_list_html(html, _site(item_selector="ul.l > li"))
        assert raw == 2
        assert [i.title for i in items] == ["这是一个足够长的政策标题"]

    def test_title_exclude_filters_unwanted(self) -> None:
        html = """<ul class="l">
          <li><a href="/a" title="习近平出席金砖国家领导人会晤">x</a><span>2026-09-15</span></li>
          <li><a href="/b" title="苏州市人民政府关于人工智能产业的若干措施">y</a><span>2026-09-15</span></li></ul>"""
        site = _site(item_selector="ul.l > li", title_exclude=["习近平", "会晤"])
        items, _ = engine.parse_list_html(html, site)
        assert [i.title for i in items] == ["苏州市人民政府关于人工智能产业的若干措施"]

    def test_dedupes_repeated_urls_within_page(self) -> None:
        html = """<ul class="l">
          <li><a href="/same" title="同一个政策文件标题A">A</a><span>2026-09-15</span></li>
          <li><a href="/same" title="同一个政策文件标题B">B</a><span>2026-09-14</span></li></ul>"""
        items, raw = engine.parse_list_html(html, _site(item_selector="ul.l > li"))
        assert raw == 2
        assert len(items) == 1

    def test_selector_matching_nothing_yields_zero_raw(self) -> None:
        items, raw = engine.parse_list_html(BEIJING_HTML, _site(item_selector="ul.nonexistent > li"))
        assert (items, raw) == ([], 0)

    def test_empty_html_is_safe(self) -> None:
        assert engine.parse_list_html("", _site()) == ([], 0)

    def test_malformed_html_does_not_raise(self) -> None:
        items, raw = engine.parse_list_html("<ul class='default_news'><li><a href='/x'", _site())
        assert isinstance(items, list)

    def test_invalid_selector_does_not_raise(self) -> None:
        items, raw = engine.parse_list_html(BEIJING_HTML, _site(item_selector="ul >>> li"))
        assert (items, raw) == ([], 0)

    def test_doc_id_is_auto_assigned(self) -> None:
        items, _ = engine.parse_list_html(BEIJING_HTML, _site())
        assert all(len(i.doc_id) == 64 for i in items)


def _tc260_site(**overrides) -> policy_config.SiteSpec:
    base = dict(
        key="tc260",
        name="TC260",
        level="national",
        region="全国",
        list_url="https://www.tc260.org.cn/front/bzzqyjList.html",
        item_selector="ul.inList > li",
        date_selector="span.date",
    )
    base.update(overrides)
    return policy_config.parse_site(base)


# ══════════════════════════════════════════════════════════
class TestScrapeSiteStatuses:
    """status 分类必须准确 —— 0 条既可能是"没有新政策"，也可能是选择器过时。"""

    def test_ok(self) -> None:
        site = _site()
        with requests_mock.Mocker() as m:
            m.get(site.list_url, text=BEIJING_HTML, status_code=200)
            result = engine.scrape_site(site)
        assert result.status == engine.STATUS_OK
        assert result.ok
        assert len(result.items) == 2
        assert result.http_status == 200

    def test_http_error(self) -> None:
        site = _site()
        with requests_mock.Mocker() as m:
            m.get(site.list_url, status_code=403, text="blocked")
            result = engine.scrape_site(site)
        assert result.status == engine.STATUS_HTTP_ERROR
        assert result.http_status == 403
        assert "403" in result.error
        assert not result.ok

    def test_timeout(self) -> None:
        site = _site()
        with requests_mock.Mocker() as m:
            m.get(site.list_url, exc=requests.exceptions.ReadTimeout)
            result = engine.scrape_site(site)
        assert result.status == engine.STATUS_TIMEOUT
        assert not result.ok

    def test_connection_error(self) -> None:
        site = _site()
        with requests_mock.Mocker() as m:
            m.get(site.list_url, exc=requests.exceptions.SSLError)
            result = engine.scrape_site(site)
        assert result.status == engine.STATUS_FETCH_ERROR
        assert "SSLError" in result.error

    def test_selector_matched_nothing_is_parse_error(self) -> None:
        """选择器命中 0 项 → 极可能改版，必须报 parse_error 而不是 empty。"""
        site = _site(item_selector="ul.gone > li")
        with requests_mock.Mocker() as m:
            m.get(site.list_url, text=BEIJING_HTML, status_code=200)
            result = engine.scrape_site(site)
        assert result.status == engine.STATUS_PARSE_ERROR
        assert result.raw_item_count == 0
        assert "selector_matched_nothing" in result.error

    def test_all_items_filtered_is_empty_not_parse_error(self) -> None:
        """命中了列表项但全被过滤 → empty（区别于选择器失效）。"""
        site = _site(min_title_length=999)
        with requests_mock.Mocker() as m:
            m.get(site.list_url, text=BEIJING_HTML, status_code=200)
            result = engine.scrape_site(site)
        assert result.status == engine.STATUS_EMPTY
        assert result.raw_item_count == 3
        assert "all_3_items_filtered" in result.error

    def test_llm_fallback_used_when_css_yields_nothing(self) -> None:
        site = _site(item_selector="ul.gone > li")
        calls: list[str] = []

        def fake_llm(html: str, s) -> list[PolicyItem]:
            calls.append(s.key)
            return [PolicyItem(site_key=s.key, title="LLM 抽取出的政策标题", url="https://a.gov.cn/llm.html")]

        with requests_mock.Mocker() as m:
            m.get(site.list_url, text=BEIJING_HTML, status_code=200)
            result = engine.scrape_site(site, llm_extractor=fake_llm)
        assert calls == ["test_site"]
        assert result.method == "llm"
        assert result.status == engine.STATUS_OK
        assert result.items[0].url == "https://a.gov.cn/llm.html"

    def test_llm_fallback_not_called_when_css_works(self) -> None:
        site = _site()
        called: list[int] = []
        with requests_mock.Mocker() as m:
            m.get(site.list_url, text=BEIJING_HTML, status_code=200)
            engine.scrape_site(site, llm_extractor=lambda h, s: called.append(1) or [])
        assert called == []

    def test_llm_fallback_exception_does_not_crash(self) -> None:
        site = _site(item_selector="ul.gone > li")

        def boom(html, s):  # noqa: ANN001
            raise RuntimeError("agent down")

        with requests_mock.Mocker() as m:
            m.get(site.list_url, text=BEIJING_HTML, status_code=200)
            result = engine.scrape_site(site, llm_extractor=boom)
        assert result.status == engine.STATUS_PARSE_ERROR
        assert "llm_fallback_failed" in result.error

    def test_llm_results_still_go_through_filters(self) -> None:
        site = _site(item_selector="ul.gone > li", title_exclude=["广告"])

        def fake_llm(html, s):  # noqa: ANN001
            return [
                PolicyItem(site_key=s.key, title="广告推广内容", url="https://a.gov.cn/1"),
                PolicyItem(site_key=s.key, title="真实的政策文件标题", url="https://a.gov.cn/2"),
            ]

        with requests_mock.Mocker() as m:
            m.get(site.list_url, text=BEIJING_HTML, status_code=200)
            result = engine.scrape_site(site, llm_extractor=fake_llm)
        assert [i.title for i in result.items] == ["真实的政策文件标题"]

    def test_log_event_receives_site_level_not_level(self) -> None:
        """log_event 首参就叫 level，字段必须叫 site_level 否则 TypeError。"""
        site = _site()
        events: list[dict] = []
        with requests_mock.Mocker() as m:
            m.get(site.list_url, text=BEIJING_HTML, status_code=200)
            engine.scrape_site(site, log_event=lambda lv, ev, **kw: events.append({"lv": lv, "ev": ev, **kw}))
        assert len(events) == 1
        assert events[0]["ev"] == "policy_source_scraped"
        assert events[0]["site_level"] == "province"
        assert "level" not in events[0]

    def test_duration_is_measured(self) -> None:
        site = _site()
        with requests_mock.Mocker() as m:
            m.get(site.list_url, text=BEIJING_HTML, status_code=200)
            result = engine.scrape_site(site)
        assert result.duration_ms >= 0


# ══════════════════════════════════════════════════════════
class TestScrapeAll:
    def test_preserves_input_order(self) -> None:
        sites = [_site(key=f"s{i}", list_url=f"https://s{i}.gov.cn/list") for i in range(5)]
        with requests_mock.Mocker() as m:
            for s in sites:
                m.get(s.list_url, text=BEIJING_HTML, status_code=200)
            results = engine.scrape_all(sites, concurrency=3)
        assert [r.site_key for r in results] == [s.key for s in sites]

    def test_one_failure_does_not_stop_others(self) -> None:
        sites = [_site(key="good", list_url="https://good.gov.cn/l"), _site(key="bad", list_url="https://bad.gov.cn/l")]
        with requests_mock.Mocker() as m:
            m.get("https://good.gov.cn/l", text=BEIJING_HTML, status_code=200)
            m.get("https://bad.gov.cn/l", status_code=502)
            results = engine.scrape_all(sites, concurrency=2)
        by_key = {r.site_key: r for r in results}
        assert by_key["good"].ok
        assert by_key["bad"].status == engine.STATUS_HTTP_ERROR

    def test_empty_input(self) -> None:
        assert engine.scrape_all([], concurrency=4) == []

    def test_unhandled_exception_becomes_fetch_error(self) -> None:
        site = _site()
        with requests_mock.Mocker() as m:
            m.get(site.list_url, text=BEIJING_HTML)
            import unittest.mock as mock

            with mock.patch.object(engine, "scrape_site", side_effect=RuntimeError("kaboom")):
                results = engine.scrape_all([site], concurrency=1)
        assert results[0].status == engine.STATUS_FETCH_ERROR
        assert "kaboom" in results[0].error


# ══════════════════════════════════════════════════════════
class TestEncodingDetection:
    def test_gbk_page_is_decoded_correctly(self) -> None:
        """政府站点常见坑：未声明 charset 时 requests 默认 ISO-8859-1，中文全乱。"""
        site = _site()
        gbk_bytes = BEIJING_HTML.encode("gbk")
        with requests_mock.Mocker() as m:
            m.get(site.list_url, content=gbk_bytes, status_code=200,
                  headers={"content-type": "text/html"})  # 不带 charset
            result = engine.scrape_site(site)
        assert result.ok
        assert "北京市文物局" in result.items[0].title

    def test_declared_utf8_is_respected(self) -> None:
        site = _site()
        with requests_mock.Mocker() as m:
            m.get(site.list_url, content=BEIJING_HTML.encode("utf-8"), status_code=200,
                  headers={"content-type": "text/html; charset=utf-8"})
            result = engine.scrape_site(site)
        assert result.ok
        assert "北京市文物局" in result.items[0].title


# ══════════════════════════════════════════════════════════
class TestSiteSpecConfig:
    @pytest.mark.parametrize("missing", ["key", "name", "level", "region", "list_url", "item_selector"])
    def test_missing_required_field_raises(self, missing: str) -> None:
        raw = dict(
            key="k", name="n", level="city", region="r",
            list_url="https://a.gov.cn/", item_selector="ul > li",
        )
        raw[missing] = ""
        with pytest.raises(ValueError, match="缺少必填字段"):
            policy_config.parse_site(raw)

    def test_invalid_level_raises(self) -> None:
        with pytest.raises(ValueError, match="level"):
            policy_config.parse_site(dict(
                key="k", name="n", level="district", region="r",
                list_url="https://a.gov.cn/", item_selector="ul > li"))

    def test_invalid_tier_raises(self) -> None:
        with pytest.raises(ValueError, match="tier"):
            policy_config.parse_site(dict(
                key="k", name="n", level="city", region="r",
                list_url="https://a.gov.cn/", item_selector="ul > li", tier="selenium"))

    def test_defaults(self) -> None:
        spec = policy_config.parse_site(dict(
            key="k", name="n", level="city", region="r",
            list_url="https://a.gov.cn/list", item_selector="ul > li"))
        assert spec.tier == "requests"
        assert spec.enabled is True
        assert spec.max_items == 200
        assert spec.min_title_length == 8
        assert spec.title_attr == "title"
        assert spec.title_exclude == ()
        assert spec.resolve_base == "https://a.gov.cn/list"

    def test_resolve_base_prefers_explicit_base_url(self) -> None:
        spec = policy_config.parse_site(dict(
            key="k", name="n", level="city", region="r",
            list_url="https://a.gov.cn/list", item_selector="ul > li",
            base_url="https://b.gov.cn/x/"))
        assert spec.resolve_base == "https://b.gov.cn/x/"

    def test_enabled_accepts_string_forms(self) -> None:
        for raw, expected in [("true", True), ("false", False), ("0", False), ("yes", True)]:
            spec = policy_config.parse_site(dict(
                key="k", name="n", level="city", region="r",
                list_url="https://a.gov.cn/", item_selector="ul > li", enabled=raw))
            assert spec.enabled is expected

    def test_title_exclude_accepts_comma_string_and_list(self) -> None:
        common = dict(key="k", name="n", level="city", region="r",
                      list_url="https://a.gov.cn/", item_selector="ul > li")
        assert policy_config.parse_site({**common, "title_exclude": "a, b ,,"}).title_exclude == ("a", "b")
        assert policy_config.parse_site({**common, "title_exclude": ["a", "b"]}).title_exclude == ("a", "b")

    def test_bad_int_falls_back_to_default(self) -> None:
        spec = policy_config.parse_site(dict(
            key="k", name="n", level="city", region="r",
            list_url="https://a.gov.cn/", item_selector="ul > li", max_items="abc"))
        assert spec.max_items == 200


class TestLoadSources:
    def _write(self, tmp_path: Path, body: str) -> Path:
        p = tmp_path / "sources.toml"
        p.write_text(textwrap.dedent(body), encoding="utf-8")
        return p

    def test_loads_and_filters_disabled(self, tmp_path: Path) -> None:
        p = self._write(tmp_path, """
            [[sites]]
            key="a"
            name="A"
            level="national"
            region="全国"
            list_url="https://a.gov.cn/"
            item_selector="ul > li"

            [[sites]]
            key="b"
            name="B"
            level="city"
            region="苏州"
            list_url="https://b.gov.cn/"
            item_selector="ul > li"
            enabled=false
        """)
        assert [s.key for s in policy_config.load_sources(p)] == ["a"]
        assert [s.key for s in policy_config.load_sources(p, include_disabled=True)] == ["a", "b"]

    def test_filter_by_level(self, tmp_path: Path) -> None:
        p = self._write(tmp_path, """
            [[sites]]
            key="n"
            name="N"
            level="national"
            region="全国"
            list_url="https://n.gov.cn/"
            item_selector="ul > li"

            [[sites]]
            key="c"
            name="C"
            level="city"
            region="苏州"
            list_url="https://c.gov.cn/"
            item_selector="ul > li"
        """)
        assert [s.key for s in policy_config.load_sources(p, only_levels={"city"})] == ["c"]
        assert [s.key for s in policy_config.load_sources(p, only_keys={"n"})] == ["n"]

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            policy_config.load_sources(tmp_path / "nope.toml")

    def test_no_sites_block_raises(self, tmp_path: Path) -> None:
        p = self._write(tmp_path, 'title = "empty"\n')
        with pytest.raises(ValueError, match="sites"):
            policy_config.load_sources(p)

    def test_duplicate_key_raises(self, tmp_path: Path) -> None:
        body = """
            [[sites]]
            key="dup"
            name="A"
            level="city"
            region="r"
            list_url="https://a.gov.cn/"
            item_selector="ul > li"
        """
        p = self._write(tmp_path, body + body)
        with pytest.raises(ValueError, match="重复"):
            policy_config.load_sources(p, include_disabled=True)

    def test_group_by_level(self, tmp_path: Path) -> None:
        p = self._write(tmp_path, """
            [[sites]]
            key="n"
            name="N"
            level="national"
            region="全国"
            list_url="https://n.gov.cn/"
            item_selector="ul > li"
        """)
        grouped = policy_config.group_by_level(policy_config.load_sources(p))
        assert len(grouped["national"]) == 1
        assert grouped["province"] == [] and grouped["city"] == []


class TestRealConfigFile:
    """仓库里的 policy_sources.toml 必须始终合法——它是配置驱动架构的入口。"""

    REPO_CONFIG = Path(__file__).resolve().parent.parent / "policy_sources.toml"

    def test_repo_config_parses(self) -> None:
        sites = policy_config.load_sources(self.REPO_CONFIG, include_disabled=True)
        assert len(sites) >= 6
        assert len({s.key for s in sites}) == len(sites)

    def test_tier_values_are_valid(self) -> None:
        for site in policy_config.load_sources(self.REPO_CONFIG, include_disabled=True):
            assert site.tier in ("requests", "playwright", "rss")

    def test_rss_tier_sites_need_no_item_selector(self) -> None:
        for site in policy_config.load_sources(self.REPO_CONFIG, include_disabled=True):
            if site.tier == "rss":
                assert site.item_selector == ""
            else:
                assert site.item_selector, f"{site.key} 是 HTML 站点却没有 item_selector"

    # 已完成真实抓取验证（dry-run ok 且入库）的 playwright 站，允许默认启用。
    _VERIFIED_PLAYWRIGHT_SITES = {"cac_sjzl", "miit_zcwj"}

    def test_no_playwright_site_is_enabled_by_default(self) -> None:
        """playwright 站点在验证选择器前不应默认启用，否则会拖慢每次运行。"""
        for site in policy_config.load_sources(self.REPO_CONFIG, include_disabled=True):
            if site.tier == "playwright" and site.key not in self._VERIFIED_PLAYWRIGHT_SITES:
                assert site.enabled is False, f"{site.key} 是 playwright 站点却默认启用"
