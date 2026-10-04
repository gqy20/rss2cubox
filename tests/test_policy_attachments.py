"""政策附件模块单测：mock 下载，真实解析内存 PDF。"""
from __future__ import annotations

from unittest.mock import patch

from rss2cubox.policy import attachments


class TestAttachmentUrl:
    def test_detects_pdf(self):
        assert attachments.is_attachment_url("https://cas.cn/2026/P0202609.pdf")
        assert attachments.is_attachment_url("https://a.gov.cn/x.docx?download=1")

    def test_rejects_html(self):
        assert not attachments.is_attachment_url("https://a.gov.cn/202609/t1.html")
        assert not attachments.is_attachment_url("")


class TestFindLinks:
    def test_finds_same_domain_pdfs(self):
        html = '<a href="/attach/rule.pdf">附件</a> <a href="https://cdn.beijing.gov.cn/x.pdf">y</a>'
        links = attachments.find_attachment_links(html, "https://www.beijing.gov.cn/zhengce/1.html")
        assert links == ["https://www.beijing.gov.cn/attach/rule.pdf"]

    def test_ignores_foreign_domain(self):
        html = '<a href="https://evil.example.com/p.pdf">x</a>'
        assert attachments.find_attachment_links(html, "https://www.gov.cn/a.html") == []

    def test_caps_at_two(self):
        html = "".join(f'<a href="/a{i}.pdf">x</a>' for i in range(5))
        assert len(attachments.find_attachment_links(html, "https://g.cn/p.html")) == 2

    def test_scanned_pdf_returns_empty(self):
        # 无法用零依赖造扫描版 PDF；以损坏字节代替——都应返回空而非抛异常
        assert attachments.extract_pdf_text(b"not a pdf") == ""


class TestFetchAttachment:
    def test_network_error_swallowed(self):
        import requests as _r

        with patch.object(attachments.requests, "get", side_effect=_r.exceptions.Timeout("t")):
            assert attachments.fetch_attachment_text("https://a.gov.cn/x.pdf") == ""

    def test_docx_not_parsed_yet(self):
        with patch.object(attachments.requests, "get") as get:
            get.return_value.status_code = 200
            get.return_value.content = b"PK\x03\x04 whatever"
            get.return_value.raise_for_status.return_value = None
            assert attachments.fetch_attachment_text("https://a.gov.cn/x.docx") == ""


class TestSocialFeedContent:
    def test_social_domains_detected(self):
        from rss2cubox.fulltext_fetcher import _is_social_url

        assert _is_social_url("https://x.com/dotey/status/2106")
        assert _is_social_url("https://twitter.com/elonmusk/status/1")
        assert not _is_social_url("https://openai.com/news/rss.xml")
        assert not _is_social_url("")
