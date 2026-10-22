import copy

import pytest

from rss2cubox.ted_report_agent import build_report


def inputs():
    draft = {"title": "", "intro": "", "topics": [], "coverage": {"articles": 11}, "cutoff_at": "2026-09-19T00:00:00Z"}
    source = {"kind": "article", "id": "a", "title": "原文标题", "url": "https://example.org/a", "publisher": "原始机构"}
    packet = {"materials": [source]}
    result = {"title": "周度观察", "intro": "本周导读", "tags": ["AI"], "next_watch": "下一步验证",
              "topics": [{"title": "议题", "claim": "判断 [1]", "body": "分析", "uncertainty": "待核实", "watch": "后续证据",
                          "sources": [{"key": "article:a", "reason": "支持这一判断", "url": "https://invented.example"}]}]}
    return draft, packet, result


def test_resolves_only_known_sources_and_preserves_snapshot_metadata():
    draft, packet, result = inputs()
    original = copy.deepcopy(draft)
    report = build_report(draft, packet, result)
    assert report["topics"][0]["sources"][0]["url"] == "https://example.org/a"
    assert report["topics"][0]["sources"][0]["title"] == "原文标题"
    assert report["coverage"] == draft["coverage"]
    assert report["cutoff_at"] == draft["cutoff_at"]
    assert report["topics"][0]["host_notes"] == ""
    assert draft == original
    assert "published" not in report
    assert report["next_watch"] == ""


@pytest.mark.parametrize("key", ["article:unknown", "policy:a", "https://invented.example"])
def test_rejects_invented_source_keys(key):
    draft, packet, result = inputs()
    result["topics"][0]["sources"][0]["key"] = key
    with pytest.raises(ValueError, match="不存在"):
        build_report(draft, packet, result)


def test_rejects_missing_or_duplicate_evidence_and_broken_citation_numbers():
    draft, packet, result = inputs()
    result["topics"][0]["claim"] = "判断 [2]"
    with pytest.raises(ValueError, match="引用编号"):
        build_report(draft, packet, result)
    result["topics"][0]["claim"] = "判断 [1]"
    result["topics"][0]["sources"] *= 2
    with pytest.raises(ValueError, match="重复"):
        build_report(draft, packet, result)
    result["topics"][0]["sources"] = []
    with pytest.raises(ValueError, match="无来源"):
        build_report(draft, packet, result)
