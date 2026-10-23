"""政策系列（series）——同类型文档跨期队列的第一等概念。

背景：阶段性变化的分析单位不是"两份文件"而是"一个系列在时间轴上的演化"
（去年同类报告 vs 今年同类报告）。本模块负责系列识别与配对：

显式系列规则（抓取源天然分组，站级）：
  - 网信办《数据出境…问答（N月）》 → monthly QA
  - 统计局数据发布 → stats_release
  - 国新办发布会 → press_conference

隐式系列（标题归一化匹配）：去掉年份与数字后标题相同、同机构或同站、
且至少相隔 60 天（排除同一文件被两站重复收录）→ generic 系列。

series key 稳定格式："<kind>:<norm-title 或 site 级规则名>"。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import psycopg

# ── 显式系列规则 ──────────────────────────────────────────

_EXPLICIT_RULES: list[tuple[str, str, str]] = [
    # (series_key, 说明, 标题正则)——更特异的规则放前面（先命中先赢）
    ("cac_data_qa", "网信办数据出境问答（月度系列）", r"数据出境.*问答"),
    ("scio_press", "国新办新闻发布会（系列）", r"国新办|国务院政策例行吹风会"),
    ("stats_release", "统计局数据发布（月度系列）", r"(采购经理指数|工业利润|消费品零售|房地产|工业增加值|国民经济运行)"),
]


def _normalize_title(title: str) -> str:
    """去掉年份与数字（保留字母/汉字），压空白。用于隐式系列匹配。"""
    # 所有数字归一为 N：1000万/2000万 同系列，（2026）/（2027）也随之同键
    t = re.sub(r"\d+", "N", title or "")
    t = re.sub(r"\s+", "", t)
    return t.strip()


@dataclass
class SeriesMatch:
    series_key: str
    is_explicit: bool
    norm_title: str


def classify(title: str, site_key: str) -> SeriesMatch | None:
    """判断一篇文档属于哪个系列。返回 None = 不属于任何已知系列。"""
    t = title or ""
    for key, _, pattern in _EXPLICIT_RULES:
        if re.search(pattern, t):
            return SeriesMatch(series_key=key, is_explicit=True, norm_title=_normalize_title(t))
    norm = _normalize_title(t)
    if len(norm) < 12:
        return None  # 太短的归一化标题没有区分度
    return SeriesMatch(series_key=f"generic:{norm[:80]}", is_explicit=False, norm_title=norm)


# ── 库操作 ────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS policy_series (
    series_key   TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,          -- explicit | generic
    description  TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS policy_series_members (
    series_key   TEXT NOT NULL REFERENCES policy_series(series_key) ON DELETE CASCADE,
    doc_id       TEXT NOT NULL REFERENCES policy_documents(id) ON DELETE CASCADE,
    added_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (series_key, doc_id)
);
CREATE INDEX IF NOT EXISTS idx_policy_series_members_doc ON policy_series_members(doc_id);
"""


def rebuild_series(db_url: str) -> dict[str, int]:
    """全量重建系列归属（幂等）。只吸收 rel≥2 且有全文的文档——
    没全文的成员没有比较价值，先不进系列。"""
    with psycopg.connect(db_url) as conn:
        conn.execute(DDL)
        rows = conn.execute(
            """SELECT id, title, site_key, published_at, first_seen_at
               FROM policy_documents
               WHERE triage_relevance >= 2
                 AND full_text IS NOT NULL AND length(full_text) > 500"""
        ).fetchall()

        series_of: dict[str, list[tuple[str, datetime]]] = {}
        for doc_id, title, site_key, pub, seen in rows:
            m = classify(title, site_key)
            if not m:
                continue
            t = pub or seen or datetime.now(timezone.utc)
            series_of.setdefault(m.series_key, []).append((doc_id, t))

        kept: dict[str, list[tuple[str, datetime]]] = {}
        for key, members in series_of.items():
            if key.startswith("generic:"):
                if len(members) < 2:
                    continue
                # 排除同文件多站重复：同日入库的重复标题只留一个
                days = sorted(m.pub_day for m in [(d, t) for d, t in members] for m in [type("X", (), {"pub_day": t.date()})()])
                unique_days = {t.date() for _, t in members}
                if len(unique_days) < 2:
                    continue
            kept[key] = members

        cur = conn.cursor()
        cur.execute("DELETE FROM policy_series_members")
        for key, members in kept.items():
            kind = "explicit" if not key.startswith("generic:") else "generic"
            cur.execute(
                """INSERT INTO policy_series (series_key, kind, description)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (series_key) DO UPDATE SET kind = EXCLUDED.kind""",
                (key, kind, kept and "" or ""),
            )
            for doc_id, _ in members:
                cur.execute(
                    "INSERT INTO policy_series_members (series_key, doc_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (key, doc_id),
                )
        conn.commit()
    return {k: len(v) for k, v in kept.items()}


def get_comparison_pairs(db_url: str, min_gap_days: int = 60) -> list[dict[str, Any]]:
    """取可比较的系列对（相邻两期）。返回 [{series_key, prev, curr}]。"""
    with psycopg.connect(db_url) as conn:
        conn.execute(DDL)
        rows = conn.execute(
            """SELECT m.series_key, d.id, d.title, d.full_text, d.url,
                      COALESCE(d.published_at, d.first_seen_at) AS t
               FROM policy_series_members m
               JOIN policy_documents d ON d.id = m.doc_id
               ORDER BY m.series_key, t"""
        ).fetchall()
    by_series: dict[str, list] = {}
    for r in rows:
        by_series.setdefault(r[0], []).append(r)
    pairs = []
    for key, items in by_series.items():
        for a, b in zip(items, items[1:]):
            gap = (b[5] - a[5]).days if a[5] and b[5] else 999
            if gap >= min_gap_days:
                pairs.append({
                    "series_key": key,
                    "prev": {"id": a[1], "title": a[2], "text": a[3], "url": a[4]},
                    "curr": {"id": b[1], "title": b[2], "text": b[3], "url": b[4]},
                })
    return pairs
