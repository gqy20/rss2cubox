"""系列识别单测（不碰库）。"""
from rss2cubox.policy.series import classify, _normalize_title


class TestExplicit:
    def test_cac_monthly_qa(self):
        m = classify("数据出境安全管理政策法规问答（2026年9月）", "cac_sjzl")
        assert m and m.series_key == "cac_data_qa" and m.is_explicit

    def test_stats_release(self):
        m = classify("2026年9月中国采购经理指数运行情况", "stats_zxfb")
        assert m and m.series_key == "stats_release"

    def test_scio_press(self):
        m = classify("国新办举行新闻发布会 介绍2026年8月份国民经济运行情况图文实录", "scio_xwfb")
        assert m and m.series_key == "scio_press"


class TestGeneric:
    def test_same_series_across_years(self):
        a = classify("北京市促进动画产业高质量发展重点项目支持办法（2026年）的通知", "beijing_zhengce")
        b = classify("北京市促进动画产业高质量发展重点项目支持办法（2027年）的通知", "beijing_zhengce")
        assert a and b and not a.is_explicit and not b.is_explicit
        assert a.series_key == b.series_key

    def test_short_title_rejected(self):
        assert classify("2026年通知", "x") is None

    def test_numbers_normalized(self):
        a = _normalize_title("补贴1000万元的标准")
        b = _normalize_title("补贴2000万元的标准")
        assert a == b  # 数字差异不构成不同系列
