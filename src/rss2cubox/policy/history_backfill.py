"""历史政策回填——为系列跨期对比补齐历史版本的全文。

背景：信源列表页只抓近几百条（旧配置 max_items=300），一两年前的政策
旧版本从未入库；且 full_text 由 LLM enrich 阶段抓取，按"新→旧 + 相关性
门槛"排队，历史文件永远轮不到。但系列对比只依赖 full_text——不需要
LLM enrich。

本脚本走最小路径：
  1. 对列表源已入库但无全文的文档，按归一化标题分组（series._normalize_title），
     只抓"有同系列伙伴"（≥2 篇）的文档正文——一次性通知没有对比价值，不抓；
  2. 废止引用目标（"《XX办法》（文号）同时废止"）优先保障；
  3. fetch_full_text 三级降级抓正文，直接 UPDATE full_text；
  4. triage 直设 2（历史文档只为系列对比，不跑 LLM 分诊）；
  5. rebuild_series 归系列并报告可比较对增量。

跑法：
    .venv/bin/python -m rss2cubox.policy.history_backfill [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import defaultdict
from typing import Any

import psycopg
from dotenv import load_dotenv

load_dotenv(".env", override=True)

from rss2cubox.fulltext_fetcher import fetch_full_text  # noqa: E402
from rss2cubox.policy.series import _normalize_title, get_comparison_pairs, rebuild_series  # noqa: E402

# 《办法名》（文号）…同时废止/予以废止
_REPEAL_PAT = re.compile(
    r"《([^《》]{6,60})》(?:（([^（）]{4,20})）)?[^。；]{0,30}?(同时废止|予以废止|废止)"
)
_MIN_TEXT_LEN = 500


def extract_repeal_names(conn: psycopg.Connection) -> set[str]:
    """在库全文里抽被废止办法名，作为优先回填目标。"""
    names: set[str] = set()
    for (text,) in conn.execute(
        """SELECT full_text FROM policy_documents
           WHERE full_text IS NOT NULL AND length(full_text) > 500"""
    ):
        for m in _REPEAL_PAT.finditer(text):
            names.add(m.group(1)[:20])
    return names


def pick_backfill_targets(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """无全文文档中，挑"有归一化标题伙伴"或"命中废止引用"的。"""
    rows = conn.execute(
        """SELECT id, title, url FROM policy_documents
           WHERE full_text IS NULL AND url LIKE 'http%' AND length(title) >= 8"""
    ).fetchall()
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for doc_id, title, url in rows:
        groups[_normalize_title(title)].append((doc_id, url))
    repeal_names = extract_repeal_names(conn)

    targets: dict[str, dict[str, Any]] = {}
    for norm, members in groups.items():
        if len(norm) < 12:
            continue
        by_repeal = any(
            any(name in t or t in name for name in repeal_names)
            for t in [m[0] for m in members]
        )
        # 伙伴 ≥2（同系列跨期候选）或直接命中废止引用
        if len(members) >= 2 or by_repeal:
            for doc_id, url in members:
                targets[doc_id] = {"id": doc_id, "url": url, "group_size": len(members)}
    return list(targets.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="历史政策回填（系列候选定向抓全文）")
    parser.add_argument("--dry-run", action="store_true", help="只报告目标清单不抓取")
    args = parser.parse_args(argv)

    db_url = os.environ["DATABASE_URL"]
    with psycopg.connect(db_url) as conn:
        targets = pick_backfill_targets(conn)
    multi = sum(1 for t in targets if t["group_size"] >= 2)
    print(f"[targets] 无全文文档中，系列候选 {len(targets)} 篇（其中同系列≥2 篇的 {multi} 篇）", flush=True)
    if args.dry_run:
        return 0

    ok = fail = 0
    with psycopg.connect(db_url) as conn:
        for t in targets:
            result = fetch_full_text(t["url"])
            if result.text and len(result.text) >= _MIN_TEXT_LEN:
                conn.execute(
                    """UPDATE policy_documents
                       SET full_text = %s, full_text_fetched_at = NOW(),
                           triage_relevance = COALESCE(triage_relevance, 2),
                           triage_is_policy = TRUE
                       WHERE id = %s""",
                    (result.text, t["id"]),
                )
                ok += 1
                print(f"  ✓ {t['id'][:8]} {len(result.text)}字 (组内{t['group_size']}篇)", flush=True)
            else:
                fail += 1
            conn.commit()
            time.sleep(1.5)  # 礼貌间隔
    print(f"[fulltext] 成功 {ok}，失败 {fail}", flush=True)

    stats = rebuild_series(db_url)
    pairs = get_comparison_pairs(db_url)
    print(f"[series] {json.dumps(stats, ensure_ascii=False)}", flush=True)
    print(f"[series] 可比较对 {len(pairs)} 个", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
