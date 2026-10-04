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


class TestExcelExtraction:
    def test_xlsx_roundtrip(self):
        import io

        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "PMI"
        ws.append(["指标", "本月", "上月"])
        ws.append(["制造业PMI", 50.1, 49.8])
        ws.append(["非制造业商务活动指数", 50.2, 49.9])
        buf = io.BytesIO()
        wb.save(buf)
        text = attachments.extract_excel_text(buf.getvalue())
        assert "[工作表: PMI]" in text
        assert "制造业PMI,50.1,49.8" in text
        assert "50.2" in text

    def test_corrupt_xlsx_returns_empty(self):
        assert attachments.extract_excel_text(b"not excel") == ""

    def test_fetch_routes_by_ext(self):
        with patch.object(attachments.requests, "get") as get:
            get.return_value.status_code = 200
            get.return_value.content = b"PK\x05\x06"  # zip 魔数但坏内容
            get.return_value.raise_for_status.return_value = None
            assert attachments.fetch_attachment_text("https://g.cn/x.xlsx") == ""
            # docx 仍不解析
            assert attachments.fetch_attachment_text("https://g.cn/x.docx") == ""
