"""政策预筛 + 结构化抽取的单元测试（不调真实 LLM）。"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
from unittest.mock import patch

import pytest

from rss2cubox.policy import enrich_agent, triage_agent
from rss2cubox.policy.config import parse_site
from rss2cubox.policy.engine import parse_rss_items


def _rss_site(**overrides):
    base = dict(
        key="rss_site", name="测试RSS", level="national", region="全国",
        list_url="https://www.gov.cn/rss.xml", tier="rss",
    )
    base.update(overrides)
    return parse_site(base)


GOV_RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
  <title>原创推荐_中国政府网</title>
  <item><title>市场监督管理所条例</title>
        <link>https://www.gov.cn/zhengce/content/202609/a.htm</link>
        <pubDate>Fri, 11 Sep 2026 08:00:00 GMT</pubDate></item>
  <item><title>国务院办公厅关于加强中小企业回款难问题治理有关工作的通知</title>
        <link>https://www.gov.cn/zhengce/content/202609/b.htm</link>
        <pubDate>Thu, 10 Sep 2026 08:00:00 GMT</pubDate></item>
  <item><title>没有链接的条目</title><pubDate>Wed, 09 Sep 2026 08:00:00 GMT</pubDate></item>
</channel></rss>
"""


class TestParseRssItems:
    """tier=rss：政府站点自带的原生 feed，比 HTML 列表页稳定得多。"""

    def test_parses_entries(self) -> None:
        items, raw = parse_rss_items(GOV_RSS, _rss_site())
        assert raw == 3
        assert len(items) == 2  # 第三条没有 link，被丢弃
        assert items[0].title == "市场监督管理所条例"
        assert items[0].url == "https://www.gov.cn/zhengce/content/202609/a.htm"

    def test_published_parsed_becomes_aware_datetime(self) -> None:
        items, _ = parse_rss_items(GOV_RSS, _rss_site())
        assert items[0].published_at == datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
        assert items[0].published_at.tzinfo is not None

    def test_max_items_caps(self) -> None:
        items, raw = parse_rss_items(GOV_RSS, _rss_site(max_items=1))
        assert raw == 3 and len(items) == 1

    def test_title_exclude_applies(self) -> None:
        items, _ = parse_rss_items(GOV_RSS, _rss_site(title_exclude=["中小企业"]))
        assert [i.title for i in items] == ["市场监督管理所条例"]

    def test_min_title_length_applies(self) -> None:
        # 「市场监督管理所条例」9 字，「国务院办公厅关于…通知」28 字
        items, _ = parse_rss_items(GOV_RSS, _rss_site(min_title_length=20))
        assert [i.title for i in items] == ["国务院办公厅关于加强中小企业回款难问题治理有关工作的通知"]

    def test_dedupes_repeated_links(self) -> None:
        dup = GOV_RSS.replace("b.htm", "a.htm")
        items, raw = parse_rss_items(dup, _rss_site())
        assert raw == 3
        assert len({i.url for i in items}) == len(items) == 1

    def test_empty_and_invalid_content(self) -> None:
        assert parse_rss_items("", _rss_site()) == ([], 0)
        items, raw = parse_rss_items("<html><body>不是 feed</body></html>", _rss_site())
        assert items == [] and raw == 0

    def test_doc_id_assigned(self) -> None:
        items, _ = parse_rss_items(GOV_RSS, _rss_site())
        assert all(len(i.doc_id) == 64 for i in items)

    def test_bytes_input_accepted(self) -> None:
        items, _ = parse_rss_items(GOV_RSS.encode("utf-8"), _rss_site())
        assert len(items) == 2


class TestCoerceEnriched:
    """模型输出的收敛层 —— 越界值降级，脏值不能进库。"""

    BASE = {
        "issuing_authority": "全国网络安全标准化技术委员会",
        "jurisdiction": "全国",
        "instrument_type": "技术标准",
        "stage": "已发布",
        "obligation_level": "推荐",
        "ai_relevance": 5,
        "ai_relevance_reason": "直接规制 AI 安全",
        "summary": "摘要",
        "key_provisions": ["条款一"],
        "source_quote": "原文引句",
        "confidence": 4,
        "_has_full_text": "1",
    }

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2026-09-15", "2026-09-15"),
            ("2026年9月15日", "2026-09-15"),
            ("自2026年10月1日起施行", "2026-10-01"),
            ("2026-09", None),          # 不完整日期 → None，不能让 PG 转型失败
            ("尚未生效", None),
            ("", None),
            (None, None),
        ],
    )
    def test_effective_date_normalized(self, raw, expected) -> None:
        """回归：模型返回中文/残缺日期时，整条 UPDATE 会因 DATE 转型失败而静默丢失。"""
        out = enrich_agent._coerce_enriched({**self.BASE, "effective_date": raw})
        assert out.get("effective_date") == expected

    def test_comment_deadline_normalized_too(self) -> None:
        out = enrich_agent._coerce_enriched({**self.BASE, "comment_deadline": "2026年10月1日"})
        assert out["comment_deadline"] == "2026-10-01"

    @pytest.mark.parametrize("field,value,fallback", [
        ("instrument_type", "不存在的位阶", "其他"),
        ("stage", "乱七八糟", "不明"),
        ("obligation_level", "必须", "不适用"),
    ])
    def test_invalid_enum_falls_back(self, field: str, value: str, fallback: str) -> None:
        out = enrich_agent._coerce_enriched({**self.BASE, field: value})
        assert out[field] == fallback

    def test_valid_enums_pass_through(self) -> None:
        out = enrich_agent._coerce_enriched({
            **self.BASE,
            "instrument_type": "地方性法规", "stage": "征求意见", "obligation_level": "强制",
        })
        assert (out["instrument_type"], out["stage"], out["obligation_level"]) == (
            "地方性法规", "征求意见", "强制")

    @pytest.mark.parametrize("value,expected", [(5, 5), (1, 1), (0, 1), (9, 1), ("5", 1), (None, 1)])
    def test_scores_clamped_to_1_5(self, value, expected) -> None:
        out = enrich_agent._coerce_enriched({**self.BASE, "ai_relevance": value, "confidence": value})
        assert out["ai_relevance"] == expected
        assert 1 <= out["confidence"] <= 5

    def test_confidence_capped_without_full_text(self) -> None:
        """只有标题没正文时，prompt 要求 confidence ≤2，但模型经常不听 —— 代码强制压。"""
        out = enrich_agent._coerce_enriched({**self.BASE, "confidence": 5, "_has_full_text": ""})
        assert out["confidence"] <= 2

    def test_confidence_not_capped_with_full_text(self) -> None:
        out = enrich_agent._coerce_enriched({**self.BASE, "confidence": 5, "_has_full_text": "1"})
        assert out["confidence"] == 5

    def test_lists_cleaned_and_capped(self) -> None:
        out = enrich_agent._coerce_enriched({
            **self.BASE,
            "affected_parties": ["  ", "生成式AI服务提供者", "", "x" * 500] + [f"p{i}" for i in range(20)],
            "key_provisions": "不是列表",
        })
        assert out["affected_parties"][0] == "生成式AI服务提供者"
        assert len(out["affected_parties"]) <= 12
        assert all(len(p) <= 300 for p in out["affected_parties"])
        assert out["key_provisions"] == []

    def test_unknown_keys_dropped(self) -> None:
        """只允许写白名单列，防止模型多吐字段污染 SQL。"""
        out = enrich_agent._coerce_enriched({**self.BASE, "hacker_field": "x", "id": "evil"})
        assert "hacker_field" not in out
        assert "id" not in out

    def test_empty_strings_become_none(self) -> None:
        out = enrich_agent._coerce_enriched({**self.BASE, "document_number": "   "})
        assert "document_number" not in out


class TestTriageBatchValidation:
    """预筛结果校验：模型编造的 id 必须被丢弃，遗漏必须被计数。"""

    DOCS = [{"id": f"id{i}", "title": f"政策标题 {i}", "region": "全国", "level": "national",
             "site_name": "s"} for i in range(4)]

    @staticmethod
    def _run(payload):
        """把 run_with_fallback 换成固定回值，不调真实 LLM。"""
        import anyio

        async def fake_fallback(coro, **kwargs):  # noqa: ANN001
            return payload

        with patch.object(triage_agent, "run_with_fallback", new=fake_fallback):
            return anyio.run(partial(triage_agent._triage_batch, TestTriageBatchValidation.DOCS, None))

    def test_accepts_valid_results(self) -> None:
        rows, reason = self._run({"results": [
            {"id": "id0", "is_policy": True, "ai_relevance": 5, "reason": "AI"},
            {"id": "id1", "is_policy": False, "ai_relevance": 1, "reason": "民生"},
        ]})
        assert len(rows) == 2
        assert rows[0]["ai_relevance"] == 5
        assert reason == "partial: missing=2 hallucinated=0"

    def test_rejects_hallucinated_ids(self) -> None:
        rows, reason = self._run({"results": [
            {"id": "id0", "is_policy": True, "ai_relevance": 4},
            {"id": "made_up_id", "is_policy": True, "ai_relevance": 5},
        ]})
        assert [r["id"] for r in rows] == ["id0"]
        assert "hallucinated=1" in reason

    def test_rejects_duplicate_ids(self) -> None:
        rows, _ = self._run({"results": [
            {"id": "id0", "is_policy": True, "ai_relevance": 4},
            {"id": "id0", "is_policy": True, "ai_relevance": 1},
        ]})
        assert len(rows) == 1
        assert rows[0]["ai_relevance"] == 4  # 保留首次出现

    def test_missing_reason_field_is_tolerated(self) -> None:
        """回归：reason 曾是 required，模型漏一个就整批 schema 失败并重试至死。"""
        rows, reason = self._run({"results": [
            {"id": f"id{i}", "is_policy": True, "ai_relevance": 3} for i in range(4)
        ]})
        assert len(rows) == 4
        assert reason == "ok"
        assert all(r["reason"] == "" for r in rows)

    def test_out_of_range_relevance_clamped(self) -> None:
        rows, _ = self._run({"results": [
            {"id": "id0", "is_policy": True, "ai_relevance": 99},
            {"id": "id1", "is_policy": True, "ai_relevance": "5"},
        ]})
        assert [r["ai_relevance"] for r in rows] == [1, 1]

    def test_invalid_payload(self) -> None:
        rows, reason = self._run({"nope": True})
        assert rows == [] and reason == "invalid_payload"

    def test_non_dict_rows_skipped(self) -> None:
        rows, _ = self._run({"results": ["垃圾", {"id": "id0", "is_policy": True, "ai_relevance": 3}]})
        assert len(rows) == 1


class TestTriageBatching:
    def test_batches_split_by_size(self) -> None:
        docs = [{"id": f"d{i}", "title": f"标题{i}"} for i in range(25)]
        captured: list[int] = []

        async def fake_all(batches, log_event, *, max_concurrent):
            captured.extend(len(b) for b in batches)
            return []

        with patch.object(triage_agent, "_triage_all", new=fake_all):
            triage_agent.triage_policy_documents(docs, batch_size=10)
        assert captured == [10, 10, 5]

    def test_empty_input_is_noop(self) -> None:
        out = triage_agent.triage_policy_documents([])
        assert out["results"] == []
        assert out["stats"]["input"] == 0

    def test_stats_count_policy_and_relevant(self) -> None:
        docs = [{"id": f"d{i}", "title": f"标题{i}"} for i in range(5)]

        async def fake_all(batches, log_event, *, max_concurrent):
            return [
                {"id": "d0", "is_policy": True, "ai_relevance": 5, "reason": ""},
                {"id": "d1", "is_policy": True, "ai_relevance": 3, "reason": ""},
                {"id": "d2", "is_policy": True, "ai_relevance": 2, "reason": ""},
                {"id": "d3", "is_policy": False, "ai_relevance": 5, "reason": ""},
                {"id": "d4", "is_policy": True, "ai_relevance": 1, "reason": ""},
            ]

        with patch.object(triage_agent, "_triage_all", new=fake_all):
            out = triage_agent.triage_policy_documents(docs, batch_size=10)
        stats = out["stats"]
        # 默认阈值 3：d0(5) 和 d1(3) 算 relevant；d3 相关度够但 is_policy=False，不算
        assert stats["policy"] == 4
        assert stats["relevant"] == 2
        assert stats["uncovered"] == 0
