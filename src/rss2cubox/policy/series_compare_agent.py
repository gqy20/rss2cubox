"""政策系列跨期比较 Agent（MVP）。

对 series.get_comparison_pairs() 给出的相邻两期调 LLM 做阶段性变化分析，
结果写 policy_series_changes 表。跑法：

    .venv/bin/python -m rss2cubox.policy.series_compare_agent [--dry-run]

prompt 见 prompts/policy_series_compare.yaml。
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
from typing import Any

from dotenv import load_dotenv

load_dotenv(".env", override=True)

import anyio  # noqa: E402
import psycopg  # noqa: E402

from rss2cubox.agent_sdk_runner import run_json_agent  # noqa: E402
from rss2cubox.policy.series import get_comparison_pairs, rebuild_series  # noqa: E402
from rss2cubox.prompt_registry import get, param  # noqa: E402

_PROMPT = get("policy_series_compare")
MAX_CHARS = param("policy_series_compare", "max_text_chars", 6000)

DDL = """
CREATE TABLE IF NOT EXISTS policy_series_changes (
    id           SERIAL PRIMARY KEY,
    series_key   TEXT NOT NULL,
    prev_doc_id  TEXT NOT NULL,
    curr_doc_id  TEXT NOT NULL,
    verdict      JSONB NOT NULL,
    diff_segments JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (series_key, prev_doc_id, curr_doc_id)
);
ALTER TABLE policy_series_changes ADD COLUMN IF NOT EXISTS diff_segments JSONB;
"""

# 段落切分：空行，或行首的中文条款编号（一、/（二）/第三条/1.）
_PARA_SPLIT = re.compile(
    r"\n\s*\n|\n(?=\s*(?:[（(]?[一二三四五六七八九十百]+|[0-9]+)[、.)．])"
)


def diff_segments(prev_text: str | None, curr_text: str | None) -> list[dict[str, Any]]:
    """段落级程序 diff（difflib 对齐，非 LLM）：写入 diff_segments 列，前端渲染原文对照。

    autojunk=False——公文里重复出现的短段（"附则"等）在 autojunk 下会被当垃圾元素导致对齐劣化。
    changed 段附字符级 prev_marks/curr_marks，前端只高亮真正变动的字，不再整段找茬。
    """

    def split(t: str | None) -> list[str]:
        return [x.strip() for x in _PARA_SPLIT.split(t or "") if x.strip()]

    prev, curr = split(prev_text), split(curr_text)
    matcher = difflib.SequenceMatcher(a=prev, b=curr, autojunk=False)
    out: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            out.extend({"type": "same", "text": p} for p in prev[i1:i2])
        elif tag == "replace":
            # 多段换多段：按序配对，多出的一侧留空，前端左右并排渲染
            for k in range(max(i2 - i1, j2 - j1)):
                p = prev[i1 + k] if i1 + k < i2 else None
                c = curr[j1 + k] if j1 + k < j2 else None
                seg: dict[str, Any] = {"type": "changed", "prev": p, "curr": c}
                if p and c:
                    pm, cm = _inline_marks(p, c)
                    if pm:
                        seg["prev_marks"] = pm
                    if cm:
                        seg["curr_marks"] = cm
                out.append(seg)
        elif tag == "delete":
            out.extend({"type": "deleted", "prev": p} for p in prev[i1:i2])
        elif tag == "insert":
            out.extend({"type": "added", "curr": c} for c in curr[j1:j2])
    return out


# 段内高亮上限：超长段的字符级 SequenceMatcher 是 O(n²)，整段重写时也没有高亮意义
_INLINE_LIMIT = 2000
# 间隔 ≤3 字符的标记合并，避免"事后<mark>支持</mark>方式"这类碎片高亮
_INLINE_GAP = 3


def _merge_marks(marks: list[list[int]]) -> list[list[int]]:
    merged: list[list[int]] = []
    for start, end in marks:
        if merged and start - merged[-1][1] <= _INLINE_GAP:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    return merged


def _inline_marks(a: str, b: str) -> tuple[list[list[int]], list[list[int]]]:
    """changed 段内的字符级差异区间 [start, end)（各自侧），供前端 <mark> 高亮。"""
    if len(a) > _INLINE_LIMIT or len(b) > _INLINE_LIMIT:
        return [], []
    a_marks: list[list[int]] = []
    b_marks: list[list[int]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "replace":
            a_marks.append([i1, i2])
            b_marks.append([j1, j2])
        elif tag == "delete":
            a_marks.append([i1, i2])
        elif tag == "insert":
            b_marks.append([j1, j2])
    return _merge_marks(a_marks), _merge_marks(b_marks)


def _build_prompt(prev: dict, curr: dict) -> str:
    return (
        f"【上期文本】（{prev['title']}，截断至{MAX_CHARS}字）\n{prev['text'][:MAX_CHARS]}\n\n"
        f"【本期文本】（{curr['title']}，截断至{MAX_CHARS}字）\n{curr['text'][:MAX_CHARS]}"
    )


def compare_pair(prev: dict, curr: dict) -> dict[str, Any] | None:
    from functools import partial

    result = anyio.run(partial(run_json_agent,
        prompt=_build_prompt(prev, curr),
        system_prompt=_PROMPT.system_prompt,
        schema=_PROMPT.output_schema,
        allowed_tools=[],
        max_turns=param("policy_series_compare", "max_turns", 4),
        timeout_seconds=param("policy_series_compare", "timeout_seconds", 180),
    ))
    return result if isinstance(result, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="政策系列跨期比较（MVP）")
    parser.add_argument("--dry-run", action="store_true", help="只打印比较结果不落库")
    parser.add_argument("--force", action="store_true", help="已入库的对也重跑")
    parser.add_argument("--selftest", action="store_true", help="跑 diff_segments 最小自检后退出")
    args = parser.parse_args(argv)

    if args.selftest:
        _selftest()
        return 0

    db_url = os.environ["DATABASE_URL"]

    # 补算存量：diff 列为空的行用两期全文重算（幂等，cron 每轮自然补齐）
    with psycopg.connect(db_url) as conn:
        conn.execute(DDL)
        pending = conn.execute(
            """SELECT c.id, p.full_text, q.full_text
               FROM policy_series_changes c
               JOIN policy_documents p ON p.id = c.prev_doc_id
               JOIN policy_documents q ON q.id = c.curr_doc_id
               WHERE c.diff_segments IS NULL"""
        ).fetchall()
    for cid, prev_text, curr_text in pending:
        segs = diff_segments(prev_text, curr_text)
        with psycopg.connect(db_url) as conn:
            conn.execute(
                "UPDATE policy_series_changes SET diff_segments=%s WHERE id=%s",
                (json.dumps(segs, ensure_ascii=False), cid),
            )
            conn.commit()
    if pending:
        print(f"[diff] 补算 {len(pending)} 行段落 diff", flush=True)

    stats = rebuild_series(db_url)
    print(f"[series] 识别 {len(stats)} 个系列: {json.dumps(stats, ensure_ascii=False)}", flush=True)

    pairs = get_comparison_pairs(db_url)
    print(f"[series] 可比较对 {len(pairs)} 个", flush=True)

    # 跳过已入库的对——cron 每轮只对新增配对调 LLM（重跑用 --force）
    if not args.force:
        done: set[tuple[str, str, str]] = set()
        with psycopg.connect(db_url) as conn:
            conn.execute(DDL)
            for row in conn.execute(
                "SELECT series_key, prev_doc_id, curr_doc_id FROM policy_series_changes"
            ):
                done.add(row)
        before = len(pairs)
        pairs = [p for p in pairs if (p["series_key"], p["prev"]["id"], p["curr"]["id"]) not in done]
        skipped = before - len(pairs)
        if skipped:
            print(f"[series] 跳过已比较 {skipped} 对（--force 重跑）", flush=True)

    for pair in pairs:
        skey = pair["series_key"]
        print(f"\n[compare] {skey}", flush=True)
        print(f"  prev: {pair['prev']['title'][:44]}", flush=True)
        print(f"  curr: {pair['curr']['title'][:44]}", flush=True)
        try:
            verdict = compare_pair(pair["prev"], pair["curr"])
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ 失败: {type(exc).__name__}: {str(exc)[:120]}", flush=True)
            continue
        if not verdict:
            print("  ✗ agent 无结构化输出", flush=True)
            continue
        print(
            f"  {'✓' if verdict.get('has_meaningful_change') else '·'} "
            f"significance={verdict.get('significance')} | {verdict.get('summary', '')[:80]}",
            flush=True,
        )
        if args.dry_run:
            print(json.dumps(verdict, ensure_ascii=False, indent=2)[:900], flush=True)
            continue
        with psycopg.connect(db_url) as conn:
            conn.execute(DDL)
            conn.execute(
                """INSERT INTO policy_series_changes (series_key, prev_doc_id, curr_doc_id, verdict, diff_segments)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (series_key, prev_doc_id, curr_doc_id)
                   DO UPDATE SET verdict = EXCLUDED.verdict,
                                 diff_segments = EXCLUDED.diff_segments,
                                 created_at = now()""",
                (skey, pair["prev"]["id"], pair["curr"]["id"],
                 json.dumps(verdict, ensure_ascii=False),
                 json.dumps(diff_segments(pair["prev"]["text"], pair["curr"]["text"]), ensure_ascii=False)),
            )
            conn.commit()
        print("  ✓ 已入库", flush=True)

    return 0


def _selftest() -> None:
    """diff_segments 的最小可运行检查：开头插入一段不得让后续段落错位。"""
    prev = ["第一章 总则", "第二条 适用范围", "第三条 罚则"]
    curr = ["第一章 总则", "新增段", "第二条 适用范围", "第三条 罚则"]
    segs = diff_segments("\n\n".join(prev), "\n\n".join(curr))
    got = [(s["type"], s.get("prev") or s.get("curr") or s.get("text")) for s in segs]
    assert got == [
        ("same", "第一章 总则"),
        ("added", "新增段"),
        ("same", "第二条 适用范围"),
        ("same", "第三条 罚则"),
    ], got
    # 单段内改措辞 → changed，字符级高亮只圈住变动的字
    seg = diff_segments("支持方式为事后奖励。", "支持方式为事后支持。")[0]
    a, b = seg["prev"], seg["curr"]
    (s, e) = seg["prev_marks"][0]
    assert a[s:e] == "奖励", seg
    (s, e) = seg["curr_marks"][0]
    assert b[s:e] == "支持", seg
    print("[selftest] diff_segments ok")


if __name__ == "__main__":
    raise SystemExit(main())
