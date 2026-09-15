"""政策列表页抓取引擎。

设计要点：
- 站点差异全部收敛到 SiteSpec 配置里，引擎本身不含任何站点专属逻辑。
- 解析出 0 条不一定代表"没有新政策"，更常见的是选择器过时。因此
  ScrapeResult 区分 ok / empty / http_error / timeout / parse_error，
  由 store.record_source_state() 统计连续空跑次数用于失效告警。
- tier=playwright 的站点走无头浏览器（复用项目已有的 playwright 依赖），
  用于工信部/发改委/江苏/杭州这类返回 JS 空壳的站点。
"""
from __future__ import annotations

import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import requests
from lxml import html as lxml_html

from rss2cubox.policy.config import SiteSpec
from rss2cubox.sync_pipeline import _normalize_url

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 2026-09-15 / 2026/09/15 / 2026.09.15 / 2026年9月15日
_DATE_RE = re.compile(r"(20\d{2})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})")

STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_HTTP_ERROR = "http_error"
STATUS_TIMEOUT = "timeout"
STATUS_PARSE_ERROR = "parse_error"
STATUS_FETCH_ERROR = "fetch_error"


@dataclass
class PolicyItem:
    """列表页解析出的一条政策文件。"""

    site_key: str
    title: str
    url: str
    published_at: datetime | None = None
    raw_date: str = ""
    doc_id: str = ""

    def __post_init__(self) -> None:
        if not self.doc_id and self.url:
            self.doc_id = stable_policy_id(self.url)


@dataclass
class ScrapeResult:
    site_key: str
    site_name: str = ""
    items: list[PolicyItem] = field(default_factory=list)
    status: str = STATUS_OK
    http_status: int = 0
    error: str = ""
    duration_ms: int = 0
    method: str = "requests"          # requests | playwright | llm
    raw_item_count: int = 0           # 过滤前命中的列表项数量

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK and bool(self.items)


def stable_policy_id(url: str) -> str:
    """与 sync_pipeline.stable_id 同样的约定：归一化 URL 后取 sha256。"""
    normalized = _normalize_url((url or "").strip()) or (url or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def parse_policy_date(raw: str) -> tuple[datetime | None, str]:
    """从文本里提取日期，返回 (aware datetime, 命中的原始片段)。"""
    text = str(raw or "")
    match = _DATE_RE.search(text)
    if not match:
        return None, ""
    year, month, day = (int(g) for g in match.groups())
    try:
        dt = datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None, match.group(0)
    return dt, match.group(0)


def _pick_encoding(response: requests.Response) -> str:
    """requests 在未声明 charset 时会默认 ISO-8859-1，中文站会乱码。"""
    declared = (response.encoding or "").lower()
    if declared and declared not in ("iso-8859-1", "latin-1", "ascii"):
        return response.encoding
    guessed = response.apparent_encoding
    return guessed or "utf-8"


def fetch_html(
    url: str,
    *,
    connect_timeout: float = 5.0,
    read_timeout: float = 20.0,
    tier: str = "requests",
    session: requests.Session | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
) -> tuple[str, int, str]:
    """抓取页面 HTML，返回 (html, http_status, error)。"""
    headers = {
        "user-agent": user_agent,
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    getter = session.get if session is not None else requests.get
    try:
        if tier == "playwright":
            return _fetch_html_playwright(url, read_timeout=read_timeout)
        response = getter(url, timeout=(connect_timeout, read_timeout), headers=headers)
    except requests.exceptions.Timeout:
        return "", 0, "timeout"
    except requests.exceptions.RequestException as exc:
        return "", 0, f"{type(exc).__name__}: {str(exc)[:160]}"

    if response.status_code != 200:
        return "", response.status_code, f"http_{response.status_code}"

    response.encoding = _pick_encoding(response)
    return response.text, response.status_code, ""


def _fetch_html_playwright(url: str, *, read_timeout: float) -> tuple[str, int, str]:
    """JS 渲染站点走无头浏览器。playwright 未安装时返回明确错误而非抛异常。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "", 0, "playwright_not_installed"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                page = browser.new_page(user_agent=DEFAULT_USER_AGENT)
                page.goto(url, wait_until="domcontentloaded", timeout=read_timeout * 1000)
                page.wait_for_timeout(1500)
                content = page.content()
                status = 200
            finally:
                browser.close()
        return content, status, ""
    except Exception as exc:  # noqa: BLE001
        return "", 0, f"playwright_{type(exc).__name__}: {str(exc)[:140]}"


def _css(node: Any, selector: str) -> list[Any]:
    if not selector:
        return []
    try:
        return list(node.cssselect(selector))
    except Exception:  # noqa: BLE001  # 选择器语法错误不应让整个批次崩掉
        return []


def _extract_text(node: Any) -> str:
    try:
        return re.sub(r"\s+", " ", (node.text_content() or "")).strip()
    except Exception:  # noqa: BLE001
        return ""


def _extract_title(item: Any, site: SiteSpec) -> str:
    nodes = _css(item, site.title_selector)
    if not nodes:
        return _extract_text(item)
    node = nodes[0]
    if site.title_attr:
        value = (node.get(site.title_attr) or "").strip()
        if value:
            return re.sub(r"\s+", " ", value)
    return _extract_text(node)


def _extract_url(item: Any, site: SiteSpec) -> str:
    nodes = _css(item, site.url_selector)
    if not nodes:
        return ""
    href = (nodes[0].get(site.url_attr) or "").strip()
    if not href:
        return ""
    if href.startswith(("http://", "https://")):
        return href
    if href.startswith(("javascript:", "#", "mailto:")):
        return ""
    return urljoin(site.resolve_base, href)


def _extract_date(item: Any, site: SiteSpec) -> tuple[datetime | None, str]:
    if site.date_selector:
        for node in _css(item, site.date_selector):
            dt, raw = parse_policy_date(_extract_text(node))
            if dt:
                return dt, raw
    # 回退：从整个列表项文本里找日期
    return parse_policy_date(_extract_text(item))


def _is_excluded(title: str, site: SiteSpec) -> bool:
    if len(title) < site.min_title_length:
        return True
    return any(pattern and pattern in title for pattern in site.title_exclude)


def parse_list_html(html: str, site: SiteSpec) -> tuple[list[PolicyItem], int]:
    """按配置解析列表页，返回 (items, 过滤前命中的列表项数)。"""
    if not html:
        return [], 0
    try:
        doc = lxml_html.fromstring(html)
    except Exception:  # noqa: BLE001
        return [], 0

    raw_items = _css(doc, site.item_selector)
    items: list[PolicyItem] = []
    seen_urls: set[str] = set()
    for node in raw_items:
        title = _extract_title(node, site)
        url = _extract_url(node, site)
        if not url or not title:
            continue
        if _is_excluded(title, site):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        published_at, raw_date = _extract_date(node, site)
        items.append(
            PolicyItem(
                site_key=site.key,
                title=title,
                url=url,
                published_at=published_at,
                raw_date=raw_date,
            )
        )
        if len(items) >= site.max_items:
            break
    return items, len(raw_items)


def scrape_site(
    site: SiteSpec,
    *,
    connect_timeout: float = 5.0,
    read_timeout: float = 20.0,
    session: requests.Session | None = None,
    llm_extractor: Callable[[str, SiteSpec], list[PolicyItem]] | None = None,
    log_event: Any = None,
) -> ScrapeResult:
    """抓取并解析单个站点。

    llm_extractor 是降级路径：CSS 解析出 0 条时（通常是站点改版），
    可以把 HTML 交给 LLM 抽结构化条目，避免整站静默失效。
    """
    started = time.perf_counter()
    result = ScrapeResult(site_key=site.key, site_name=site.name, method=site.tier)

    html, http_status, error = fetch_html(
        site.list_url,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        tier=site.tier,
        session=session,
    )
    result.http_status = http_status
    result.duration_ms = int((time.perf_counter() - started) * 1000)

    if error == "timeout":
        result.status = STATUS_TIMEOUT
        result.error = "timeout"
        _emit(log_event, result, site)
        return result
    if error:
        result.status = STATUS_HTTP_ERROR if error.startswith("http_") else STATUS_FETCH_ERROR
        result.error = error
        _emit(log_event, result, site)
        return result

    items, raw_count = parse_list_html(html, site)
    result.raw_item_count = raw_count

    if not items and llm_extractor is not None:
        try:
            llm_items = llm_extractor(html, site)
        except Exception as exc:  # noqa: BLE001
            llm_items = []
            result.error = f"llm_fallback_failed: {type(exc).__name__}"
        if llm_items:
            items = [i for i in llm_items if i.url and not _is_excluded(i.title, site)][: site.max_items]
            result.method = "llm"

    result.items = items
    if items:
        result.status = STATUS_OK
    elif raw_count == 0:
        # 选择器一条都没命中 —— 极可能是站点改版，标记为解析错误以便告警
        result.status = STATUS_PARSE_ERROR
        result.error = result.error or f"selector_matched_nothing: {site.item_selector}"
    else:
        # 命中了列表项但全被过滤掉（标题过短/命中排除词/无链接）
        result.status = STATUS_EMPTY
        result.error = result.error or f"all_{raw_count}_items_filtered"

    result.duration_ms = int((time.perf_counter() - started) * 1000)
    _emit(log_event, result, site)
    return result


def _emit(log_event: Any, result: ScrapeResult, site: SiteSpec) -> None:
    if log_event is None:
        return
    level = "INFO" if result.ok else "WARN"
    # 注意：log_event 的第一个形参就叫 level，所以站点级别字段必须改名，否则冲突
    log_event(
        level,
        "policy_source_scraped",
        stage="policy_fetch",
        site_key=site.key,
        site_name=site.name,
        site_level=site.level,
        region=site.region,
        status=result.status,
        items=len(result.items),
        raw_items=result.raw_item_count,
        http_status=result.http_status,
        method=result.method,
        duration_ms=result.duration_ms,
        error=result.error,
    )


def scrape_all(
    sites: list[SiteSpec],
    *,
    concurrency: int = 4,
    connect_timeout: float = 5.0,
    read_timeout: float = 20.0,
    llm_extractor: Callable[[str, SiteSpec], list[PolicyItem]] | None = None,
    log_event: Any = None,
) -> list[ScrapeResult]:
    """并发抓取全部站点。保持输入顺序返回。"""
    if not sites:
        return []
    workers = max(1, min(int(concurrency or 1), len(sites)))
    results: dict[str, ScrapeResult] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                scrape_site,
                site,
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
                llm_extractor=llm_extractor,
                log_event=log_event,
            ): site
            for site in sites
        }
        for future in as_completed(futures):
            site = futures[future]
            try:
                results[site.key] = future.result()
            except Exception as exc:  # noqa: BLE001
                results[site.key] = ScrapeResult(
                    site_key=site.key,
                    site_name=site.name,
                    status=STATUS_FETCH_ERROR,
                    error=f"unhandled_{type(exc).__name__}: {str(exc)[:160]}",
                )
    return [results[site.key] for site in sites if site.key in results]
