"""
全文抓取模块 — 三级降级策略

L1: trafilatura 直连（静态站，~1s）
L2: Playwright 渲染 + 正文提取（JS SPA 站，~7-10s）
L3: Playwright 微信专用（mp.weixin.qq.com，~9-10s）
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class FetchResult:
    text: str = ""
    source: str = ""  # 'trafilatura' | 'playwright_css' | 'wechat'
    level: int = 0       # 1 | 2 | 3
    elapsed_s: float = 0.0
    error: str = ""


# ── 环境变量 ──────────────────────────────────────────────
FULLTEXT_ENABLED = os.getenv("FULLTEXT_ENABLED", "true").lower() not in ("false", "0", "no")
FULLTEXT_MAX_WORKERS = max(1, int(os.getenv("FULLTEXT_MAX_WORKERS", "10")))
FULLTEXT_ITEM_TIMEOUT_S = max(5, int(os.getenv("FULLTEXT_ITEM_TIMEOUT_S", "30")))

# 每级内部超时分配（总和不超过 FULLTEXT_ITEM_TIMEOUT_S）
_L1_TIMEOUT_S = min(10, FULLTEXT_ITEM_TIMEOUT_S // 3)       # trafilatura 上限 ~10s
_L2_TIMEOUT_S = min(20, FULLTEXT_ITEM_TIMEOUT_S // 2)      # Playwright 上限 ~20s
_L3_TIMEOUT_S = min(15, FULLTEXT_ITEM_TIMEOUT_S // 2)      # 微信上限 ~15s

# Playwright 浏览器超时（单次页面加载）
_PLAYWRIGHT_NAVIGATION_TIMEOUT_S = max(8, min(20, int(os.getenv("PLAYWRIGHT_NAVIGATION_TIMEOUT_S", "15"))))
# 渲染后额外等待 JS 的时间
_RENDER_EXTRA_WAIT_S = max(1, min(3, int(os.getenv("RENDER_EXTRA_WAIT_S", "2"))))


def _is_wechat_url(url: str) -> bool:
    host = (url or "").strip().split("/")[2] if "//" in url else ""
    return "mp.weixin.qq.com" in host or "weixin.qq.com" in host


def _fetch_with_timeout(fetch_fn: Callable, url: str, timeout_s: float) -> FetchResult | None:
    """在子线程中执行 fetch_fn(url)，超过 timeout_s 秒返回 None（不阻塞调用线程）。"""
    result_container: list[FetchResult | None] = [None]
    exception_holder: list[BaseException | None] = [None]

    def _worker() -> None:
        try:
            result_container[0] = fetch_fn(url)
        except BaseException as exc:
            exception_holder[0] = exc

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=timeout_s)

    if t.is_alive():
        return None  # 超时，子线程会被 GC 回收（daemon=True）
    if exception_holder[0] is not None:
        return None
    return result_container[0]


# ── Level 1: trafilatura 直连 ────────────────────────────
def _fetch_l1_trafilatura(url: str) -> FetchResult | None:
    import trafilatura

    t0 = time.perf_counter()
    try:
        downloaded = trafilatura.fetch_url(url, no_ssl=True)
        if not downloaded:
            return None
        text = trafilatura.extract(
            downloaded,
            output_format="txt",
            include_links=False,
            include_comments=True,
            include_tables=True,
            include_formatting=True,
        )
        if not text or len(text.strip()) < 80:
            return None
        return FetchResult(text=text.strip(), source="trafilatura", level=1, elapsed_s=time.perf_counter() - t0)
    except Exception:
        return None


# ── Level 2: Playwright 渲染 + 智能提取 ───────────────────
def _fetch_l2_playwright(url: str) -> FetchResult | None:
    from playwright.sync_api import sync_playwright

    t0 = time.perf_counter()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
            try:
                ctx = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                )
                page = ctx.new_page()
                resp = page.goto(url, wait_until="domcontentloaded", timeout=_PLAYWRIGHT_NAVIGATION_TIMEOUT_S * 1000)
                # 不再因 4xx/5xx 直接放弃——部分站点返回非标准状态码但正文可用

                # 等待 JS 渲染完成（缩短超时）
                try:
                    page.wait_for_load_state("networkidle", timeout=6_000)
                except Exception:
                    pass
                time.sleep(_RENDER_EXTRA_WAIT_S)

                body_len = page.evaluate("() => (document.body?.innerText || '').length")
                if not body_len or body_len < 100:
                    return None

                rendered_html = page.content()

                # 策略 A: trafilatura 从渲染后 HTML 提取
                import trafilatura as _tf
                txt_a = _tf.extract(
                    rendered_html,
                    output_format="txt",
                    include_links=False,
                    include_comments=True,
                    include_tables=True,
                    include_formatting=True,
                )

                # 策略 B: CSS 选择器精准定位正文区域
                txt_b = page.evaluate("""() => {
                    const sels = [
                        ['article', 'article'],
                        ['.markdown-body', '.markdown-body'],
                        ['.article-content-container', '.article-content-container'],
                        ['.rich-text-container', '.rich-text-container'],
                        ['.article-content', '.article-content'],
                        ['.article-content-wrapper', '.article-content-wrapper'],
                        ['.common-width', '.common-width'],
                        ['#article_content', '#article_content'],
                        ['main', 'main'],
                    ];
                    let best = null;
                    for (const [name, sel] of sels) {
                        const el = document.querySelector(sel);
                        if (el && el.innerText.trim().length > (best?.len || 0)) {
                            best = { name, len: el.innerText.trim().length, text: el.innerText.trim() };
                        }
                    }
                    return best ? best.text : null;
                }""")

                browser.close()

                candidates = []
                if txt_a and len(txt_a.strip()) > 100:
                    candidates.append(("trafilatura", txt_a))
                if txt_b and len(txt_b.strip()) > 150:
                    candidates.append(("css_selector", txt_b))

                if not candidates:
                    return None

                best_name, best_text = max(candidates, key=lambda x: len(x[1]))
                return FetchResult(text=best_text, source=best_name, level=2, elapsed_s=time.perf_counter() - t0)
            finally:
                browser.close()
    except Exception:
        return None


# ── Level 3: 微信专用 ─────────────────────────────────────
def _fetch_l3_wechat(url: str) -> FetchResult | None:
    from playwright.sync_api import sync_playwright

    mobile_ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
        "Mobile/15E148 Safari/604.1"
    )

    t0 = time.perf_counter()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
            try:
                ctx = browser.new_context(user_agent=mobile_ua)
                page = ctx.new_page()
                page.set_extra_http_headers({
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Referer": "https://mp.weixin.qq.com/",
                })

                def block_media(route):
                    if route.request.resource_type in {"image", "media", "font"}:
                        route.abort()
                        return
                    route.continue_()

                page.route("**/*", block_media)
                page.goto(url, wait_until="domcontentloaded", timeout=_PLAYWRIGHT_NAVIGATION_TIMEOUT_S * 1000)
                time.sleep(3)  # 微信已屏蔽媒体资源，3s 足够渲染

                has_content = page.evaluate("() => !!document.querySelector('#js_content')")
                if not has_content:
                    browser.close()
                    return None

                payload = page.evaluate("""() => {
                    const el = document.querySelector('#js_content');
                    const titleEl = document.querySelector('#activity-name') || document.querySelector('.rich_media_title');
                    const nameEl = document.querySelector('#js_name') || document.querySelector('.rich_media_meta_nickname');
                    return {
                        title: titleEl ? titleEl.innerText.trim() : '',
                        account: nameEl ? nameEl.innerText.trim() : '',
                        text: el ? el.innerText.trim() : '',
                    };
                }""")

                browser.close()

                text = payload.get("text", "")
                if not text or len(text) < 30:
                    return None

                result = f"【标题】{payload['title']}\n【公众号】{payload['account']}\n\n{text}"
                return FetchResult(text=result, source="wechat", level=3, elapsed_s=time.perf_counter() - t0)
            finally:
                browser.close()
    except Exception:
        return None


# ── 单条抓取（三级降级入口） ─────────────────────
def fetch_full_text(url: str) -> FetchResult:
    """对单个 URL 执行三级降级全文抓取（每级有独立超时）。"""
    url = (url or "").strip()
    if not url:
        return FetchResult(error="empty_url")

    t0 = time.perf_counter()

    if _is_wechat_url(url):
        result = _fetch_with_timeout(_fetch_l3_wechat, url, _L3_TIMEOUT_S)
        return result or FetchResult(error="wechat_failed", level=3, elapsed_s=time.perf_counter() - t0)

    # L1: trafilatura（快速，~1-10s）
    result = _fetch_with_timeout(_fetch_l1_trafilatura, url, _L1_TIMEOUT_S)
    if result and result.text:
        result.elapsed_s = time.perf_counter() - t0
        return result

    # L2: Playwright（较慢，~7-20s）
    remaining = FULLTEXT_ITEM_TIMEOUT_S - (time.perf_counter() - t0)
    if remaining > 5:
        result = _fetch_with_timeout(_fetch_l2_playwright, url, min(remaining - 1, _L2_TIMEOUT_S))
        if result and result.text:
            result.elapsed_s = time.perf_counter() - t0
            return result

    return FetchResult(error="all_levels_failed", elapsed_s=time.perf_counter() - t0)


# ── 并发批量抓取 ─────────────────────────────────────
def fetch_fulltext_batch(
    items: list[dict[str, Any]],
    *,
    max_workers: int | None = None,
    log_event: Callable[..., None] | None = None,
) -> dict[str, FetchResult]:
    """并发批量抓取候选条目的全文。

    Args:
        items: 候选列表，每项需包含 eid 和 url 字段。
        max_workers: 最大并发数，默认 FULLTEXT_MAX_WORKERS。
        log_event: 日志回调。

    Returns:
        dict[eid, FetchResult]
    """
    if not items:
        return {}

    workers = max_workers or FULLTEXT_MAX_WORKERS
    results: dict[str, FetchResult] = {}
    stats = {"total": len(items), "l1": 0, "l2": 0, "l3": 0, "failed": 0}

    def _run_one(item: dict[str, Any]) -> None:
        eid = str(item.get("eid", "")).strip()
        url = str(item.get("url", "")).strip()
        if not eid or not url:
            stats["failed"] += 1
            return

        started = time.perf_counter()
        if log_event:
            log_event("INFO", "fulltext_start", eid=eid, url=url[:120])

        result = fetch_full_text(url)
        result.elapsed_s = time.perf_counter() - started

        if result.text:
            results[eid] = result
            level_key = f"l{result.level}"
            if level_key in stats:
                stats[level_key] += 1
            if log_event:
                log_event(
                    "INFO",
                    "fulltext_done",
                    eid=eid,
                    source=result.source,
                    level=result.level,
                    char_count=len(result.text),
                    duration_ms=int(result.elapsed_s * 1000),
                )
        else:
            stats["failed"] += 1
            if log_event:
                log_event(
                    "WARN",
                    "fulltext_failed",
                    eid=eid,
                    error=result.error or "unknown",
                    duration_ms=int(result.elapsed_s * 1000),
                )

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run_one, item): item for item in items}
        for future in concurrent.futures.as_completed(futures):
            pass  # _run_one 内部已处理结果和异常

    if log_event:
        log_event(
            "INFO",
            "fulltext_batch_complete",
            total=stats["total"],
            l1=stats["l1"],
            l2=stats["l2"],
            l3=stats["l3"],
            failed=stats["failed"],
            succeeded=len(results),
        )

    return results
