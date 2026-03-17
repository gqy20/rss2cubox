from rss2cubox import webpage_reader


def test_is_wechat_article_url() -> None:
    assert webpage_reader.is_wechat_article_url("https://mp.weixin.qq.com/s/abc")
    assert webpage_reader.is_wechat_article_url("https://mp.weixin.qq.com.cn/s/abc")
    assert not webpage_reader.is_wechat_article_url("https://example.com/post")


def test_html_to_markdown_basic() -> None:
    html = "<h1>标题</h1><p>第一段<strong>加粗</strong></p><img data-src='https://a/b.jpg' />"
    markdown = webpage_reader.html_to_markdown(html)
    assert "# 标题" in markdown
    assert "第一段**加粗**" in markdown


def test_html_to_markdown_skips_data_images_but_keeps_remote_images() -> None:
    html = (
        '<p>前文</p>'
        '<img src="data:image/gif;base64,AAAA" />'
        '<img data-src="https://img.example.com/a.png" />'
    )
    markdown = webpage_reader.html_to_markdown(html)
    assert "data:image/gif" not in markdown
    assert "![](https://img.example.com/a.png)" in markdown


def test_read_webpage_text_uses_jina_for_non_wechat(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        webpage_reader,
        "_fetch_via_jina",
        lambda url, jina_reader_base, jina_max_chars: f"jina:{url}:{jina_reader_base}:{jina_max_chars}",
    )
    ok, content, source = webpage_reader.read_webpage_text(
        "https://example.com/post",
        jina_reader_base="https://r.jina.ai/",
        jina_max_chars=500,
        wechat_timeout_seconds=30,
    )
    assert ok is True
    assert content.startswith("jina:https://example.com/post")
    assert source == "jina"


def test_read_webpage_text_uses_wechat_fetcher_first(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        webpage_reader,
        "fetch_wechat_article",
        lambda url, timeout_seconds: {"markdown": "wechat markdown", "text": "", "url": url},
    )
    ok, content, source = webpage_reader.read_webpage_text(
        "https://mp.weixin.qq.com/s/abc",
        jina_reader_base="https://r.jina.ai/",
        jina_max_chars=500,
        wechat_timeout_seconds=30,
    )
    assert ok is True
    assert content == "wechat markdown"
    assert source == "wechat_playwright"


def test_read_webpage_text_falls_back_to_jina_for_wechat(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def _raise(url: str, timeout_seconds: int):  # noqa: ANN001
        raise RuntimeError("boom")

    monkeypatch.setattr(webpage_reader, "fetch_wechat_article", _raise)
    monkeypatch.setattr(webpage_reader, "_fetch_via_jina", lambda *args, **kwargs: "fallback markdown")
    ok, content, source = webpage_reader.read_webpage_text(
        "https://mp.weixin.qq.com/s/abc",
        jina_reader_base="https://r.jina.ai/",
        jina_max_chars=500,
        wechat_timeout_seconds=30,
    )
    assert ok is True
    assert content == "fallback markdown"
    assert source == "jina_fallback"
