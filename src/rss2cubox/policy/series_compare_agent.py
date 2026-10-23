"""政策系列跨期比较 Agent（MVP）。

对 series.get_comparison_pairs() 给出的相邻两期调 LLM 做阶段性变化分析，
结果写 policy_series_changes 表。跑法：

    .venv/bin/python -m rss2cubox.policy.series_compare_agent [--dry-run]

prompt 见 prompts/policy_series_compare.yaml。
"""
from __future__ import annotations

import argparse
import json
import os
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
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (series_key, prev_doc_id, curr_doc_id)
);
"""


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
    args = parser.parse_args(argv)

    db_url = os.environ["DATABASE_URL"]
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
                """INSERT INTO policy_series_changes (series_key, prev_doc_id, curr_doc_id, verdict)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (series_key, prev_doc_id, curr_doc_id)
                   DO UPDATE SET verdict = EXCLUDED.verdict, created_at = now()""",
                (skey, pair["prev"]["id"], pair["curr"]["id"], json.dumps(verdict, ensure_ascii=False)),
            )
            conn.commit()
        print("  ✓ 已入库", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
