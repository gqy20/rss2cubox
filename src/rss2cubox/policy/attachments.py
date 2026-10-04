"""政策附件（PDF 等）下载与解析。

政策的"肉"常在附件里：正文页只有通知壳，条款/数据表在 PDF。本模块负责
- 判断 URL 是否附件直链（列表页 PDF 链接，如中科院制度文件）
- 从详情页原始 HTML 里发现附件链接（北京政策的"附件：实施细则.pdf"）
- 下载并提取文本（pypdf；docx/xlsx 暂只识别不解析，记 TODO）

扫描版 PDF（无文字层）返回空文本并靠调用方记 meta——不上 OCR，成本墙。
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import requests

from rss2cubox.policy.engine import DEFAULT_USER_AGENT

ATTACH_EXTS = (".pdf", ".xlsx")
TODO_EXTS = (".doc", ".docx", ".xls")  # 识别但暂不解析（.xls 老格式低频）
MAX_ATTACHMENTS_PER_DOC = 2
_MAX_BYTES = 20 * 1024 * 1024  # 20MB 上限，政府大公报 PDF 也够


def is_attachment_url(url: str) -> bool:
    path = (urlparse(url or "").path or "").lower()
    return any(path.endswith(ext) for ext in ATTACH_EXTS + TODO_EXTS)


def extract_pdf_text(data: bytes) -> str:
    """提取 PDF 文字层。扫描版（无文字层）返回空串。"""
    import io

    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = []
        for page in reader.pages[:80]:  # 80 页封顶，enrich 只喂 12k 字符
            try:
                pages.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001  # 单页损坏不拖垮整份
                continue
        return re.sub(r"[ \t]+", " ", "\n".join(pages)).strip()
    except (PdfReadError, Exception):  # noqa: BLE001  # 加密/损坏/非 PDF
        return ""


def extract_excel_text(data: bytes) -> str:
    """xlsx 提取为文本：每 sheet 输出表名 + CSV 风格行（前 40 行）。

    政府统计表的语义在"指标名 + 数值"的行列结构里，CSV 化保结构喂 enrich。
    """
    import io

    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001
        return ""
    parts: list[str] = []
    for ws in wb.worksheets[:6]:  # 最多 6 个 sheet
        rows: list[str] = []
        for r, row in enumerate(ws.iter_rows(values_only=True)):
            if r >= 40:
                rows.append(f"…（共 {ws.max_row or '?'} 行，截断）")
                break
            cells = []
            for c in row[:20]:  # 最多 20 列
                v = "" if c is None else (f"{c:.4f}".rstrip("0").rstrip(".") if isinstance(c, float) else str(c))
                cells.append(v.replace("\n", " ").strip())
            line = ",".join(cells).strip(",").rstrip(",")
            if line:
                rows.append(line)
        if rows:
            parts.append(f"[工作表: {ws.title}]\n" + "\n".join(rows))
    wb.close()
    return "\n\n".join(parts).strip()


def fetch_attachment_text(url: str, *, timeout: float = 30.0) -> str:
    """下载附件并提取文本。失败/扫描版返回空串。"""
    try:
        resp = requests.get(
            url, timeout=timeout, headers={"user-agent": DEFAULT_USER_AGENT}
        )
        resp.raise_for_status()
        if len(resp.content or b"") > _MAX_BYTES:
            return ""
        path = (urlparse(url).path or "").lower()
        if path.endswith(".pdf"):
            return extract_pdf_text(resp.content)
        if path.endswith(".xlsx"):
            return extract_excel_text(resp.content)
        return ""  # doc/docx/xls 暂不解析
    except requests.exceptions.RequestException:
        return ""


def find_attachment_links(html: str, base_url: str) -> list[str]:
    """从详情页原始 HTML 里发现附件链接（限内链/相对路径，防外链注入）。"""
    if not html:
        return []
    base_host = urlparse(base_url).hostname or ""
    seen: list[str] = []
    for href in re.findall(r'href=["\']([^"\']{4,300})["\']', html, re.I):
        href = href.strip()
        low = urlparse(urljoin(base_url, href)).path.lower()
        if not any(low.endswith(ext) for ext in ATTACH_EXTS + TODO_EXTS):
            continue
        absolute = urljoin(base_url, href)
        host = urlparse(absolute).hostname or ""
        # 同域或子域（政府站的附件 CDN 常是子域），拒绝完全无关外域
        if base_host and host and not (
            host == base_host or host.endswith("." + base_host) or base_host.endswith("." + host)
        ):
            continue
        if absolute not in seen:
            seen.append(absolute)
        if len(seen) >= MAX_ATTACHMENTS_PER_DOC:
            break
    return seen
