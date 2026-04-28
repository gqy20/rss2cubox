from __future__ import annotations

from html import unescape
import re
from typing import Any
from urllib.parse import urlparse

import requests


def is_wechat_article_url(url: str) -> bool:
    host = urlparse(str(url or "").strip()).netloc.lower()
    return host in {"mp.weixin.qq.com", "mp.weixin.qq.com.cn"}


def html_to_markdown(html: str) -> str:
    text = str(html or "")
    if not text:
        return ""

    replacements = [
        (r"<h1[^>]*>(.*?)</h1>", r"# \1\n\n"),
        (r"<h2[^>]*>(.*?)</h2>", r"## \1\n\n"),
        (r"<h3[^>]*>(.*?)</h3>", r"### \1\n\n"),
        (r"<strong[^>]*>(.*?)</strong>", r"**\1**"),
        (r"<em[^>]*>(.*?)</em>", r"*\1*"),
        (r"<br\s*/?>", "\n"),
        (r"</p>", "\n\n"),
        (r"<p[^>]*>", ""),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE | re.DOTALL)

    def _replace_img(match: re.Match[str]) -> str:
        url = (match.group(1) or "").strip()
        if not url or url.startswith("data:image/"):
            return "\n\n"
        return f"\n\n![]({url})\n\n"

    text = re.sub(
        r'<img[^>]*(?:data-src|src)="([^"]+)"[^>]*>',
        _replace_img,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_wechat_article(url: str, timeout_seconds: int = 30) -> dict[str, Any]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - import path tested indirectly
        raise RuntimeError("playwright_not_installed") from exc

    mobile_ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
        "Mobile/15E148 Safari/604.1"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        try:
            context = browser.new_context(user_agent=mobile_ua)
            page = context.new_page()
            page.set_extra_http_headers(
                {
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Referer": "https://mp.weixin.qq.com/",
                }
            )
            def _handle_route(route):  # type: ignore[no-untyped-def]
                if route.request.resource_type in {"image", "media", "font"}:
                    route.abort()
                    return
                route.continue_()

            page.route("**/*", _handle_route)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
                try:
                    page.wait_for_selector("#js_content", timeout=10_000)
                except PlaywrightTimeoutError:
                    pass

                payload = page.evaluate(
                    """
                    () => {
                      const pickText = (...selectors) => {
                        for (const selector of selectors) {
                          if (!selector) continue;
                          const el = document.querySelector(selector);
                          const text = el ? (el.innerText || "").trim() : "";
                          if (text) return text;
                        }
                        return "";
                      };
                      const pickMeta = (property, attr = "property") => {
                        const el = document.querySelector(`meta[${attr}="${property}"]`);
                        return el ? (el.getAttribute("content") || "").trim() : "";
                      };
                      const globalValue = (key) => {
                        const value = globalThis[key];
                        return typeof value === "string" ? value.trim() : "";
                      };
                      const contentEl = document.querySelector("#js_content");
                      const timestamp = Number(globalThis.ct || globalThis.publish_time || 0);
                      const publishDate = timestamp > 0
                        ? new Date(timestamp * 1000).toISOString()
                        : pickText("#publish_time", "#js_publish_time", ".publish_time", ".rich_media_meta.rich_media_meta_text");
                      return {
                        title:
                          pickText("#activity-name", ".rich_media_title") ||
                          pickMeta("og:title", "property") ||
                          globalValue("msg_title") ||
                          document.title ||
                          "",
                        account_name:
                          pickText("#js_name", ".account_nickname", ".wx_follow_nickname", ".profile_nickname", ".rich_media_meta_nickname a") ||
                          globalValue("nickname") ||
                          globalValue("user_name"),
                        author:
                          pickText("#js_author_name", ".meta_content #js_author_name", ".rich_media_meta_text#js_author_name") ||
                          globalValue("author_name"),
                        publish_date: publishDate,
                        html: contentEl ? contentEl.innerHTML : "",
                        text: contentEl ? (contentEl.innerText || "").trim() : ""
                      };
                    }
                    """
                )
                html = str(payload.get("html", "")).strip()
                if not html:
                    raise RuntimeError("wechat_content_not_found")
                payload["url"] = url
                payload["markdown"] = html_to_markdown(html)
                return payload
            finally:
                try:
                    page.unroute("**/*", _handle_route)
                except Exception:
                    pass
                try:
                    page.close()
                except Exception:
                    pass
                try:
                    context.close()
                except Exception:
                    pass
        finally:
            browser.close()


def _fetch_via_jina(url: str, jina_reader_base: str, jina_max_chars: int) -> str:
    resp = requests.get(
        f"{jina_reader_base}{url}",
        headers={"Accept": "text/plain", "x-respond-with": "markdown"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.text[:jina_max_chars]


def _fetch_via_playwright(url: str, max_chars: int, timeout_seconds: int = 30) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("playwright_not_installed") from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            # wait a bit for JS rendering
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
            text = page.evaluate("() => (document.body?.innerText || document.documentElement?.innerText || '').trim()")
            if not text:
                html = page.evaluate("() => document.body?.innerHTML || ''")
                text = html_to_markdown(html)
            return text[:max_chars]
        finally:
            browser.close()


def read_webpage_text(
    url: str,
    *,
    jina_reader_base: str,
    jina_max_chars: int,
    wechat_timeout_seconds: int,
) -> tuple[bool, str, str]:
    target_url = str(url or "").strip()
    if not target_url:
        return False, "missing_url", "none"

    if is_wechat_article_url(target_url):
        try:
            payload = fetch_wechat_article(target_url, timeout_seconds=wechat_timeout_seconds)
            text = str(payload.get("markdown") or payload.get("text") or "").strip()
            if text:
                return True, text[:jina_max_chars], "wechat_playwright"
            return False, "wechat_empty_content", "wechat_playwright"
        except Exception as exc:
            try:
                text = _fetch_via_jina(target_url, jina_reader_base, jina_max_chars)
                return True, text, "jina_fallback"
            except Exception as jina_exc:
                return False, f"wechat_fetch_failed:{exc}; jina_fetch_failed:{jina_exc}", "fallback_failed"

    # 非微信文章：优先 Jina Reader，失败后降级到 Playwright 真实浏览器渲染
    try:
        return True, _fetch_via_jina(target_url, jina_reader_base, jina_max_chars), "jina"
    except Exception as jina_exc:
        try:
            text = _fetch_via_playwright(target_url, jina_max_chars)
            if text.strip():
                return True, text, "playwright_fallback"
            return False, "playwright_fallback_empty", "playwright_fallback"
        except Exception as pw_exc:
            return False, f"jina_fetch_failed:{jina_exc}; playwright_fallback_failed:{pw_exc}", "all_failed"
