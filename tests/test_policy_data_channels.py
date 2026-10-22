"""真实公开接口形状的回归样例，不访问网络、不提交表单。"""
from unittest.mock import Mock, patch

import pytest

from rss2cubox.policy import data_channels as channels
from rss2cubox.policy.config import parse_site
from rss2cubox.policy.engine import scrape_site


def site(adapter="ndsms_datasets", **kw):
    return parse_site(dict(key=adapter, name="公开数据平台", level="national", region="全国",
                           list_url="https://www.ndsms.cn/", tier="api", adapter=adapter, **kw))


def dataset(rid="one", **kw):
    return dict(id=rid, datasetName="质量追溯训练数据集", datasetDesc="包含设备参数和模型解析建议",
                supplierName="供给企业", taskName="多模态/其他", openScope=0,
                createdTime="2026-10-20T10:11:22", updatedTime="2026-10-21T10:37:58", **kw)


def payload(rows, total=None):
    return dict(code=200, success=True, data=dict(list=rows, total=len(rows) if total is None else total,
                                               pageTotal=len(rows)))


def response(value):
    r = Mock()
    r.json.return_value = value
    return r


def test_requires_known_fixed_api_adapter():
    with pytest.raises(ValueError, match="适配器"):
        site("arbitrary_url_fetcher")
    with pytest.raises(ValueError, match="adapter"):
        parse_site(dict(key="k", name="n", level="national", region="全国",
                        list_url="https://example.org/", tier="api"))


def test_catalogue_snapshot_stable_identity_dates_and_nonmaterial_counters():
    first = channels._ndsms_item(site(), dataset(downloadCount=1, collectionCount=1))
    second = channels._ndsms_item(site(), dataset(downloadCount=999, collectionCount=23))
    assert first.doc_id == second.doc_id
    assert first.source_metadata == second.source_metadata
    assert first.full_text == second.full_text
    assert first.url == channels.NDSMS + "/dataRetrieval/datasetDetail/?id=one"
    assert first.published_at is None  # created/updated 不冒充发布
    assert first.source_updated_at.utcoffset().total_seconds() == 8 * 3600
    assert first.content_kind == "数据集目录"
    changed = channels._ndsms_item(site(), {**dataset(), "datasetDesc": "新的许可证与用途描述"})
    assert changed.doc_id == first.doc_id and changed.full_text != first.full_text


def test_demands_capture_description_without_contact_fields():
    row = dict(id="need", title="骨密度相关数据", description="用于人工智能应用研究。联系：13812345678 a@b.cn",
               status=0, supplierName="公开发布方", updatedTime="2026-10-15")
    item = channels._ndsms_item(site("ndsms_demands"), row)
    assert item.url == channels.NDSMS + "/requirements/need"
    assert "人工智能应用研究" in item.full_text
    assert "13812345678" not in item.full_text and "a@b.cn" not in item.full_text
    assert item.source_metadata["需求状态代码"] == "0"
    assert item.published_at is None


@pytest.mark.parametrize("value", [{}, {"success": False}, {"success": True, "code": 200, "data": {}},
                                    {"success": True, "code": 200, "data": {"list": [], "total": "1"}}])
def test_api_schema_and_business_failures_are_not_empty_success(value):
    with pytest.raises(ValueError):
        channels._rows(value)


def test_failure_is_recorded_in_standard_source_monitor():
    client = Mock()
    client.post.return_value = response({"success": False})
    result = scrape_site(site(), session=client)
    assert result.status == "fetch_error"
    assert "business status" in result.error
    assert not result.ok


def test_pagination_uses_total_and_deduplicates_ids():
    client = Mock()
    client.post.side_effect = [response(payload([dataset(str(n)) for n in range(50)], 52)),
                               response(payload([dataset("50"), dataset("51")], 52))]
    items = channels.scrape_data_channel(site(max_items=52), session=client)
    assert len(items) == 52
    assert client.post.call_args_list[1].kwargs["json"]["pageIndex"] == 2


def test_repeated_page_is_an_error():
    client = Mock()
    client.post.return_value = response(payload([dataset()], 500))
    with pytest.raises(ValueError, match="repeated"):
        channels.scrape_data_channel(site(max_items=100), session=client)


def test_disclosure_reads_all_detail_pages_but_excludes_contacts():
    def read(path, body):
        if "queryInformationDisclosure" in path:
            return dict(success=True, errorCode="0", total=1, data=[dict(uuid="institution", disclosureName="某市数据局",
                         disclosureEmail="private@example.com", disclosureTelephone="13812345678")])
        if body["pageNum"] == 1:
            rows = [dict(dataRegistName="资源" + str(i), authOperatEntityName="运营企业",
                         dataRegistStandard="500元/千条", implementTimeControl="2025") for i in range(100)]
        else:
            rows = [dict(dataRegistName="资源100", implementTimeControl="2025")]
        return dict(success=True, errorCode="0", total=101, data=rows)

    item, = channels._sjd_disclosures(site("sjd_disclosures", max_items=1), read)
    assert "资源100" in item.full_text and "500元/千条" in item.full_text
    assert "13812345678" not in item.full_text and "private@example.com" not in item.full_text
    assert item.published_at is None
    assert item.url == "https://sjdj.nda.gov.cn/userHome"
    assert channels._date("2025年度") is None


def test_policy_lists_are_not_limited_to_homepage_featured_content():
    calls = []
    def read(path, body):
        calls.append(body)
        return dict(success=True, errorCode="0", total=1, data=[dict(uuid=body["regionType"] or "notice",
            title="公开数据资源管理政策", policyInfo="<p>第一条 公共数据开发利用。</p><p>第二条 登记。</p>", releaseTime="2025-09-05")])
    items = channels._sjd_policies(site("sjd_policies"), read)
    assert len(items) == 3
    assert {c["regionType"] for c in calls} == {"00", "01", ""}
    assert "。\n第二条" in items[0].full_text
    assert items[0].published_at.isoformat().startswith("2025-09-05T00:00:00+08:00")


@pytest.mark.asyncio
async def test_resource_analysis_cannot_invent_legal_obligations():
    from unittest.mock import AsyncMock
    from rss2cubox.policy import enrich_agent

    doc = {"id": "one", "title": "骨密度相关数据", "content_kind": "用数需求"}
    wrong = dict(summary="需求说明", source_quote="人工智能应用研究", instrument_type="法律",
                 obligation_level="强制", effective_date="2026-10-01", issuing_authority="错误推断",
                 document_number="伪造文号", comment_deadline="2026-11-01", confidence=5, stage="已生效")
    with patch.object(enrich_agent, "run_with_fallback", AsyncMock(return_value=wrong)), \
         patch.object(enrich_agent, "_jev_lineage_check"):
        result, reason = await enrich_agent._enrich_one(doc, "骨密度数据用于人工智能应用研究")
    assert reason == "ok"
    assert result["instrument_type"] == "用数需求" and result["obligation_level"] == "不适用"
    assert all(result[k] is None for k in ["effective_date", "issuing_authority", "document_number", "comment_deadline"])
    with patch.object(enrich_agent, "run_with_fallback", AsyncMock(return_value=wrong)):
        result, reason = await enrich_agent._enrich_one(doc, "完全不同的原文")
    assert result is None and reason == "source_quote_not_in_snapshot"


def test_multi_source_triage_cli_does_not_expand_to_unrelated_backlog():
    from rss2cubox import policy_runner as runner

    with patch.object(runner, "ensure_policy_schema", return_value=True), \
         patch.object(runner, "_run_triage_stage") as triage, \
         patch.object(runner, "count_policy_documents", return_value={}), \
         patch.object(runner, "count_policy_triage", return_value={}):
        assert runner.main(["--triage", "--only", "ndsms_datasets,ndsms_demands"]) == 0
    assert triage.call_args.kwargs["site_key"] == {"ndsms_datasets", "ndsms_demands"}


@pytest.mark.asyncio
async def test_resource_triage_keeps_relevance_without_calling_it_a_law():
    from unittest.mock import AsyncMock
    from rss2cubox.policy import triage_agent

    with patch.object(triage_agent, "run_with_fallback", AsyncMock(return_value={"results": [
        {"id": "one", "is_policy": True, "ai_relevance": 5}]})):
        rows, reason = await triage_agent._triage_batch([
            {"id": "one", "title": "骨密度数据", "content_kind": "用数需求"}])
    assert reason == "ok" and rows[0]["is_policy"] is False and rows[0]["ai_relevance"] == 5


def test_no_fulltext_fetch_still_analyzes_saved_snapshot():
    from unittest.mock import AsyncMock
    from rss2cubox.policy import enrich_agent

    with patch.object(enrich_agent, "_enrich_all", AsyncMock(return_value={})) as enrich:
        enrich_agent.enrich_policy_documents([
            {"id": "one", "full_text": "公开目录实际内容"}], fetch_full_text_enabled=False)
    assert enrich.call_args.args[1] == {"one": "公开目录实际内容"}


@pytest.mark.asyncio
async def test_resource_quotes_constrained_to_actual_snapshot_without_mutating_global_schema():
    from unittest.mock import AsyncMock
    from rss2cubox.policy import enrich_agent

    body = "骨密度相关数据\n需求说明：依托科研项目从事人工智能应用研究。数据用于模型评测。"
    doc = {"id": "one", "content_kind": "用数需求"}
    options = enrich_agent._snapshot_quote_options(doc, body)
    assert options and all(q in body and 4 <= len(q) <= 120 for q in options)
    with patch.object(enrich_agent, "run_with_fallback", AsyncMock(return_value={})) as run:
        await enrich_agent._enrich_one(doc, body)
    schema = run.call_args.args[0].keywords["schema"]
    assert schema["properties"]["source_quote"]["enum"] == options
    assert "enum" not in enrich_agent.POLICY_ENRICH_SCHEMA["properties"]["source_quote"]
    assert enrich_agent._snapshot_quote_options({"content_kind": "政策文件"}, body)
    assert enrich_agent._snapshot_quote_options({}, body) == []


@pytest.mark.asyncio
async def test_api_policy_quote_validation_and_candidates_cover_the_end_of_body():
    from unittest.mock import AsyncMock
    from rss2cubox.policy import enrich_agent

    body = "\n".join("第" + str(i) + "条 数据共享管理要求。" for i in range(100))
    doc = {"id": "policy", "content_kind": "政策文件"}
    options = enrich_agent._snapshot_quote_options(doc, body)
    assert len(options) == 24 and "第0条" in options[0] and "第99条" in options[-1]
    with patch.object(enrich_agent, "run_with_fallback", AsyncMock(return_value={
        "summary": "政策摘要", "source_quote": "模型改写了不存在的条文"})):
        out, reason = await enrich_agent._enrich_one(doc, body)
    assert out is None and reason == "source_quote_not_in_snapshot"
