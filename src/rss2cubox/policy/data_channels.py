"""固定政府数据平台的公开元数据适配器；不登录、不下载数据、不提交登记。

接口是原站网页的匿名读取接口，不是承诺长期稳定的开发者 API。
校验业务状态和结构，失败交给 policy_source_state 告警，不用空列表掩盖。
"""
from __future__ import annotations

import hashlib
import re
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from lxml import html

from .config import SiteSpec
from .engine import PolicyItem

# 与 engine._DIRECT_SESSION 同策略：公开政府接口统一直连，绕过系统代理
_DIRECT = requests.Session()
_DIRECT.trust_env = False

NDSMS = "https://www.ndsms.cn"
NDSMS_API = NDSMS + "/api/cedc-dsm-backend-main/public"
SJD = "https://sjdj.nda.gov.cn"
RESOURCE_KINDS = frozenset({"数据集目录", "用数需求", "授权运营披露"})


def _text(value: Any) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    if "<" in value and ">" in value:
        value = re.sub(r"</(?:p|div|li|h[1-6]|tr)>", "\n", value, flags=re.I)
        node = html.fromstring("<div>" + value + "</div>")
        for element in node.xpath(".//script | .//style"):
            element.drop_tree()
        value = node.text_content()
    # 只保留需求/资源说明，公开联系方式不进入分析与再传播。
    value = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[联系电话已省略]", value)
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[联系邮箱已省略]", value)
    return value.strip()


def _date(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}(?:T| |$)", raw):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    except ValueError:
        return None


def _rows(payload: Any, *, sjd: bool = False) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("public API business status failed")
    if not sjd and payload.get("code") != 200:
        raise ValueError("unexpected public API code")
    if sjd:
        if str(payload.get("errorCode")) != "0":
            raise ValueError("unexpected registration API code")
        rows, total = payload.get("data"), payload.get("total")
    else:
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("public API data must be an object")
        rows, total = data.get("list"), data.get("total")
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ValueError("public API list schema changed")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise ValueError("public API total schema changed")
    return rows, total


def _item(site: SiteSpec, record_id: Any, title: Any, url: str, kind: str,
          fields: dict[str, Any], *, updated: Any = None, published: Any = None) -> PolicyItem:
    record_id, title = str(record_id or "").strip(), _text(title)
    if not record_id or not title:
        raise ValueError("public record missing ID or title")
    metadata = {k: _text(v) for k, v in fields.items() if v is not None and str(v).strip()}
    metadata["原站记录ID"] = record_id
    body = title + "\n" + "\n".join(f"{k}：{v}" for k, v in metadata.items())
    return PolicyItem(
        site_key=site.key, title=title, url=url,
        doc_id=hashlib.sha256(f"{site.key}:{record_id}".encode()).hexdigest(),
        published_at=_date(published), raw_date=str(published or ""),
        full_text=body, content_kind=kind, source_metadata=metadata,
        source_updated_at=_date(updated),
    )


def _ndsms_item(site: SiteSpec, row: dict[str, Any]) -> PolicyItem:
    rid = str(row.get("id") or "")
    if row.get("openScope") not in (None, 0):
        raise ValueError("unexpected non-public record scope")
    if site.adapter == "ndsms_datasets":
        return _item(site, rid, row.get("datasetName"),
                     NDSMS + "/dataRetrieval/datasetDetail/?id=" + quote(rid, safe=""),
                     "数据集目录", {
                         "数据集简介": row.get("datasetDesc"),
                         "供给方": row.get("supplierName"), "行业": row.get("industryName"),
                         "领域": row.get("datasetKeyDomainName"), "分类": row.get("contentName"),
                         "任务模态": row.get("taskName"), "知识产权说明": row.get("iprInfo"),
                         "标签": "、".join(sorted(row.get("tags") or [])),
                         "数据量（原站值）": row.get("size"), "容量单位代码": row.get("sizeUnit"),
                         "访问范围代码": row.get("openScope"),
                         "原站创建时间": row.get("createdTime"),
                     }, updated=row.get("updatedTime"))
    return _item(site, rid, row.get("title"), NDSMS + "/requirements/" + quote(rid, safe=""),
                 "用数需求", {
                     "需求说明": row.get("description"), "发布方": row.get("supplierName"),
                     "行业": row.get("assignedIndustryName"), "领域": row.get("keyDomainName"),
                     "任务模态": row.get("taskName"), "需求状态代码": row.get("status"),
                     "原站创建时间": row.get("createdTime"),
                 }, updated=row.get("updatedTime"))


def _fetch_ndsms(site: SiteSpec, timeout: float, session: requests.Session) -> list[PolicyItem]:
    items: dict[str, PolicyItem] = {}
    size = min(50, max(1, site.max_items))
    # 有界分页；pageTotal 是本页条数，不是总页数。
    for page in range(1, (max(1, site.max_items) + size - 1) // size + 1):
        if site.adapter == "ndsms_datasets":
            response = session.post(NDSMS_API + "/navigate/datasetList",
                                    json={"pageIndex": page, "pageSize": size}, timeout=timeout)
        else:
            response = session.get(NDSMS_API + "/requirement/list",
                                   params={"pageNo": page, "pageSize": size}, timeout=timeout)
        response.raise_for_status()
        rows, total = _rows(response.json())
        if not rows and (page - 1) * size < total:
            raise ValueError("public API returned an incomplete page")
        previous = len(items)
        for row in rows:
            item = _ndsms_item(site, row)
            items[item.doc_id] = item
        if rows and previous == len(items):
            raise ValueError("public API repeated a page")
        if len(items) >= site.max_items or page * size >= total:
            break
    return list(items.values())[:site.max_items]


@contextmanager
def _sjd_reader(timeout: float) -> Iterator[Any]:
    """原站需浏览器 TLS；只在该固定源使用 browser-native fetch。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            context = browser.new_context(locale="zh-CN", ignore_https_errors=True)
            page = context.new_page()
            page.goto(SJD + "/userHome", wait_until="domcontentloaded", timeout=timeout * 1000)

            def read(path: str, body: dict[str, Any]) -> Any:
                return page.evaluate("""async ({path, body, timeout}) => {
                    const response = await fetch(path, {
                        method: 'POST', headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(body), signal: AbortSignal.timeout(timeout)
                    });
                    if (!response.ok) throw new Error('public HTTP ' + response.status);
                    return await response.json();
                }""", {"path": path, "body": body, "timeout": int(timeout * 1000)})

            yield read
        finally:
            browser.close()


def _sjd_policies(site: SiteSpec, read: Any) -> list[PolicyItem]:
    items: dict[str, PolicyItem] = {}
    rows: list[dict[str, Any]] = []
    # 原站国家/地方政策分区，另采通知列表；不用首页精选替代完整列表。
    for region, policy_type in (("00", ""), ("01", ""), ("", "02")):
        size = min(site.max_items, 50)
        for page in range(1, (site.max_items + size - 1) // size + 1):
            batch, total = _rows(read("/register/statistics/registPolicy/queryPolicyInfo", {
                "pageNum": page, "pageSize": size, "policyType": policy_type,
                "regionType": region, "keyword": "",
            }), sjd=True)
            if not batch and (page - 1) * size < total:
                raise ValueError("registration policies pagination incomplete")
            rows.extend(batch)
            if page * size >= total:
                break
    for row in rows:
        item = _item(site, row.get("uuid"), row.get("title"), SJD + "/userHome", "政策文件", {
            "正文": row.get("policyInfo"),
            "原站标注机构": row.get("dataBureauName"),
            "原站阅读路径": "登记政策，按标题查找；该平台无逐条独立链接",
            "日期说明": "发布日期为平台标注的 releaseTime，文件成文与生效日期以正文为准",
        }, published=row.get("releaseTime"))
        items[item.doc_id] = item
    return list(items.values())[:site.max_items]


DISCLOSURE_FIELDS = {
    "dataRegistName": "公共数据资源名称", "intendRegister": "登记情况代码",
    "authOperatEntityMode": "授权运营方式代码", "dataRegistStandard": "运营服务上限收费标准",
    "authOperatEntityName": "运营机构名称", "authOperatEntityTime": "授权运营期限",
    "implementTimeControl": "信息披露年度",
}


def _sjd_disclosures(site: SiteSpec, read: Any) -> list[PolicyItem]:
    items: dict[str, PolicyItem] = {}
    size = min(20, max(1, site.max_items))
    seen_institutions: set[str] = set()
    for page in range(1, (max(1, site.max_items) + size - 1) // size + 1):
        institutions, total = _rows(read("/register/statistics/basicImplement/queryInformationDisclosure", {
            "institutionLabel": "1", "inputName": "", "provinceCode": "", "institutionName": "",
            "pageNum": page, "pageSize": size,
        }), sjd=True)
        if not institutions and (page - 1) * size < total:
            raise ValueError("disclosure institution pagination incomplete")
        for institution in institutions:
            rid = str(institution.get("uuid") or "")
            if not rid or not institution.get("disclosureName"):
                raise ValueError("disclosure institution missing ID or name")
            if rid in seen_institutions:
                raise ValueError("disclosure institution page repeated")
            seen_institutions.add(rid)
            # 明确展开每家机构全部披露行，不能拿联系人目录充当披露正文。
            records: list[dict[str, Any]] = []
            for detail_page in range(1, 51):
                rows, detail_total = _rows(read(
                    "/register/statistics/basicImplement/detailImplementInformationDisclosure",
                    {"uuid": rid, "pageNum": detail_page, "pageSize": 100}), sjd=True)
                if not rows and len(records) < detail_total:
                    raise ValueError("disclosure detail pagination incomplete")
                records.extend({label: _text(r.get(key)) for key, label in DISCLOSURE_FIELDS.items()}
                               for r in rows)
                if detail_page * 100 >= detail_total:
                    break
            else:
                raise ValueError("disclosure detail exceeds bounded pagination")
            records.sort(key=lambda r: tuple(r.values()))
            if not records:
                continue
            body = "\n\n".join("\n".join(f"{k}：{v}" for k, v in r.items() if v) for r in records)
            item = _item(site, rid, _text(institution.get("disclosureName")) + "公共数据授权运营信息披露",
                         SJD + "/userHome", "授权运营披露", {
                             "实施机构": institution.get("disclosureName"), "披露内容": body,
                             "原站阅读路径": "信息披露 → 实施机构 → 按机构名称查找详情；无逐条独立链接",
                         })
            items[item.doc_id] = item
        if page * size >= total or len(items) >= site.max_items:
            break
    return list(items.values())[:site.max_items]


def scrape_data_channel(site: SiteSpec, *, timeout: float = 30,
                        session: requests.Session | None = None) -> list[PolicyItem]:
    if site.max_items <= 0:
        raise ValueError("max_items must be positive")
    if site.adapter == "govcn_zcwjk":
        return _fetch_govcn_zcwjk(site, timeout, session or _DIRECT)
    if site.adapter in {"ndsms_datasets", "ndsms_demands"}:
        if session is not None:
            return _fetch_ndsms(site, timeout, session)
        with requests.Session() as client:
            return _fetch_ndsms(site, timeout, client)
    with _sjd_reader(timeout) as read:
        if site.adapter == "sjd_policies":
            return _sjd_policies(site, read)
        if site.adapter == "sjd_disclosures":
            return _sjd_disclosures(site, read)
        raise ValueError("unsupported public API adapter")


# ── gov.cn 政策文件库检索接口 ──────────────────────────────
# 接口要求 q 非空；公文标题几乎都含"的"，用它近似全量，按发布时间倒序翻页。
# 回溯深度由 max_items 控制（每页 20 条），历史远至 2005 年。
GOVCN_SEARCH = "https://sousuo.www.gov.cn/search-gov/data"
_GOVCN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124",
    "Referer": "https://sousuo.www.gov.cn/zcwjk/policyRetrieval",
    "Accept": "application/json",
}


def _fetch_govcn_zcwjk(site: SiteSpec, timeout: float,
                       session: requests.Session) -> list[PolicyItem]:
    items: list[PolicyItem] = []
    seen: set[str] = set()
    per_page = 20
    max_pages = max(1, (site.max_items + per_page - 1) // per_page)
    for channel in ("zhengcelibrary_gw", "zhengcelibrary_bm"):
        for page in range(1, max_pages + 1):
            params = {"t": channel, "q": "的", "timetype": "", "sort": "pubtime",
                      "sortType": "1", "searchfield": "title", "p": str(page),
                      "n": str(per_page), "type": "gwyzcwjk"}
            resp = session.get(GOVCN_SEARCH, params=params, headers=_GOVCN_HEADERS,
                               timeout=timeout)
            resp.raise_for_status()
            body = resp.json()
            if body.get("code") != 200:
                raise ValueError(f"govcn_zcwjk code={body.get('code')}")
            rows = (body.get("searchVO") or {}).get("listVO") or []
            if not rows:
                break
            for row in rows:
                url = str(row.get("url") or "").strip()
                title = re.sub(r"<[^>]+>", "", str(row.get("title") or "")).strip()
                if not url or len(title) < 6 or url in seen:
                    continue
                seen.add(url)
                published, raw = _govcn_date(row.get("pubtimeStr"))
                items.append(PolicyItem(
                    site_key=site.key, title=title, url=url,
                    published_at=published, raw_date=raw,
                    content_kind="policy",
                    source_metadata={
                        "document_number": str(row.get("pcode") or ""),
                        "issuing_authority": str(row.get("puborg") or ""),
                        "channel": "国务院文件" if channel.endswith("gw") else "部门文件",
                    },
                ))
                if len(items) >= site.max_items:
                    return items
            time.sleep(1)  # 礼貌限速
    return items


def _govcn_date(value: Any) -> tuple[datetime | None, str]:
    raw = str(value or "").strip()
    m = re.match(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", raw)
    if not m:
        return None, raw
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3])), raw
    except ValueError:
        return None, raw
