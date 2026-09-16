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
# L2（playwright）总开关。关掉后只用 trafilatura，抓不到就退回摘要。
# 存在的理由：L2 每个 URL 都 chromium.launch() 一次，在 runner 进程内与主流程
# 并发时会严重拖慢整体（实测全文阶段 0.6 篇/分钟，隔离测试同样配置 38 篇/分钟），
# 且连 L1 都会被拖到超时。排查这类问题时可以先关掉它做对照。
FULLTEXT_ENABLE_PLAYWRIGHT = os.getenv("FULLTEXT_ENABLE_PLAYWRIGHT", "true").lower() not in ("false", "0", "no")

# 每级内部超时分配（总和不超过 FULLTEXT_ITEM_TIMEOUT_S）
_L1_TIMEOUT_S = min(10, FULLTEXT_ITEM_TIMEOUT_S // 3)       # trafilatura 上限 ~10s
_L2_TIMEOUT_S = min(20, FULLTEXT_ITEM_TIMEOUT_S // 2)      # Playwright 上限 ~20s
_L3_TIMEOUT_S = min(15, FULLTEXT_ITEM_TIMEOUT_S // 2)      # 微信上限 ~15s

# Playwright 浏览器超时（单次页面加载）
_PLAYWRIGHT_NAVIGATION_TIMEOUT_S = max(8, min(20, int(os.getenv("PLAYWRIGHT_NAVIGATION_TIMEOUT_S", "15"))))
# 渲染后额外等待 JS 的时间
_RENDER_EXTRA_WAIT_S = max(1, min(3, int(os.getenv("RENDER_EXTRA_WAIT_S", "2"))))

# L2 的内部预算（launch + goto + render wait）必须显著小于它的外层预算
# _L2_TIMEOUT_S，否则外层 _fetch_with_timeout 会在 playwright 完成前就砍掉它，
# 而且被丢弃的子线程会继续持有浏览器。
#
# 默认值就是这个坑：nav=15 + launch~2 + wait=2 ≈ 19s，而 _L2_TIMEOUT_S 最多 20s
# （min(20, T//2) 硬封顶，把 FULLTEXT_ITEM_TIMEOUT_S 调多大都没用），余量为零，
# 只要有一点并发争抢就必然全部超时（实测一次完整运行 22 次尝试 0 成功）。
# 这里把 nav 自动钳制到外层预算的一半，让错误配置无法成立。
_PLAYWRIGHT_NAVIGATION_TIMEOUT_S = max(
    4, min(_PLAYWRIGHT_NAVIGATION_TIMEOUT_S, int(_L2_TIMEOUT_S * 0.5))
)
_RENDER_EXTRA_WAIT_S = max(1, min(_RENDER_EXTRA_WAIT_S, max(1, int(_L2_TIMEOUT_S * 0.1))))


_L1_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _is_wechat_url(url: str) -> bool:
    host = (url or "").strip().split("/")[2] if "//" in url else ""
    return "mp.weixin.qq.com" in host or "weixin.qq.com" in host


def _fetch_with_timeout(fetch_fn: Callable, url: str, timeout_s: float) -> FetchResult | None:
    """在子线程中执行 fetch_fn(url)，不阻塞调用线程。

    失败时返回**带 error 的 FetchResult** 而不是 None，因为调用方需要区分
    三种形态：超时 / 抛异常 / 跑完但没抽到正文。原来统一返回 None，
    最后只能报一个笼统的 all_levels_failed，排查时完全无从下手。
    """
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
        # 超时，子线程会被 GC 回收（daemon=True）
        return FetchResult(error=f"timeout>{timeout_s:.0f}s")
    if exception_holder[0] is not None:
        exc = exception_holder[0]
        return FetchResult(error=f"{type(exc).__name__}: {str(exc)[:100]}")
    if result_container[0] is None:
        return FetchResult(error="no_content")
    return result_container[0]


# ── Level 1: trafilatura 直连 ────────────────────────────
def _l1_download(url: str) -> str:
    """用 requests 下载 HTML，失败返回空串。

    必须自己下载而不是用 trafilatura.fetch_url：后者基于 urllib3.PoolManager，
    **不读 HTTP(S)_PROXY 环境变量**。而本机访问大部分境外站点必须走本地代理
    （实测 huggingface.co 走代理 200/1.7s，直连 20s 超时）。
    用 fetch_url 会直连并挂到超时（实测 30.1s 失败），而 requests 会读代理
    环境变量（实测 1.2~1.5s 成功）。这一个差别导致了全文抓取阶段
    在真实运行里 0/368 全部失败。
    """
    import requests

    # 下载超时必须给外层 L1 预算留余量，否则又是“内部≈外层”的老坑
    download_timeout = max(3.0, min(8.0, _L1_TIMEOUT_S - 1))
    try:
        response = requests.get(
            url,
            timeout=(4.0, download_timeout),
            headers={"user-agent": _L1_USER_AGENT, "accept-language": "en,zh-CN;q=0.9"},
        )
        response.raise_for_status()
    except Exception:  # noqa: BLE001
        return ""
    # 未声明 charset 时 requests 会默认 ISO-8859-1，中文站会乱码
    if not response.encoding or response.encoding.lower() in ("iso-8859-1", "latin-1", "ascii"):
        response.encoding = response.apparent_encoding or "utf-8"
    return response.text or ""


def _fetch_l1_trafilatura(url: str) -> FetchResult | None:
    import trafilatura

    t0 = time.perf_counter()
    try:
        downloaded = _l1_download(url)
        if not downloaded:
            # 回退到 trafilatura 自己的下载器（它有自己的重试与 robots 处理）
            downloaded = trafilatura.fetch_url(url, no_ssl=True) or ""
        if not downloaded:
            return FetchResult(error="l1_download_failed", level=1, elapsed_s=time.perf_counter() - t0)
        text = trafilatura.extract(
            downloaded,
            output_format="txt",
            include_links=False,
            include_comments=True,
            include_tables=True,
            include_formatting=True,
        )
        if not text or len(text.strip()) < 80:
            return FetchResult(
                error=f"l1_text_too_short:{len((text or '').strip())}",
                level=1,
                elapsed_s=time.perf_counter() - t0,
            )
        return FetchResult(text=text.strip(), source="trafilatura", level=1, elapsed_s=time.perf_counter() - t0)
    except Exception as exc:  # noqa: BLE001
        return FetchResult(
            error=f"l1_{type(exc).__name__}: {str(exc)[:100]}", level=1,
            elapsed_s=time.perf_counter() - t0,
        )


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
    levels: list[str] = []

    if _is_wechat_url(url):
        result = _fetch_with_timeout(_fetch_l3_wechat, url, _L3_TIMEOUT_S)
        if result and result.text:
            result.elapsed_s = time.perf_counter() - t0
            return result
        return FetchResult(
            error=f"wechat_failed: l3={getattr(result, 'error', '') or 'empty'}",
            level=3,
            elapsed_s=time.perf_counter() - t0,
        )

    # L1: trafilatura（快速，~1-10s）
    result = _fetch_with_timeout(_fetch_l1_trafilatura, url, _L1_TIMEOUT_S)
    if result and result.text:
        result.elapsed_s = time.perf_counter() - t0
        return result
    levels.append(f"l1={getattr(result, 'error', '') or 'empty'}")

    # L2: Playwright（较慢，~7-20s）
    remaining = FULLTEXT_ITEM_TIMEOUT_S - (time.perf_counter() - t0)
    if not FULLTEXT_ENABLE_PLAYWRIGHT:
        levels.append("l2=disabled")
    elif remaining > 5:
        l2_budget = min(remaining - 1, _L2_TIMEOUT_S)
        result = _fetch_with_timeout(_fetch_l2_playwright, url, l2_budget)
        if result and result.text:
            result.elapsed_s = time.perf_counter() - t0
            return result
        levels.append(f"l2={getattr(result, 'error', '') or 'empty'}")
    else:
        levels.append(f"l2=skipped_budget_left={remaining:.0f}s")

    return FetchResult(
        error="all_levels_failed: " + " | ".join(levels),
        elapsed_s=time.perf_counter() - t0,
    )


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
