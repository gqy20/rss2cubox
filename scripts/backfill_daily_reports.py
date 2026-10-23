#!/usr/bin/env python3
"""补生成历史日报。

用法: .venv/bin/python scripts/backfill_daily_reports.py 2026-10-19 2026-10-20 [ ... ]
日期参数为 YYYY-MM-DD，可多个。幂等（ON CONFLICT 覆盖同期）。

前提：当天的 enrich 分析已回填——日报原料是"当日有分析的文章"，
缺 enrich 的日期补出来会是空报告或直接跳过（最小阈值拦截）。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from rss2cubox.daily_report_agent import run_daily_report  # noqa: E402
from rss2cubox.db_client import save_daily_report  # noqa: E402


def main(dates: list[str]) -> int:
    for raw in dates:
        report_date = raw.strip()[:10]
        if len(report_date) != 10:
            print(f"[skip] {raw}: 日期格式应为 YYYY-MM-DD", flush=True)
            continue
        print(f"[backfill] {report_date} 生成中…", flush=True)
        payload = run_daily_report(report_date=report_date)
        if not payload:
            print(f"[backfill] {report_date}: agent 无产出（当天可能无分析数据）", flush=True)
            continue
        if save_daily_report(payload):
            print(
                f"[backfill] {report_date}: 已入库 "
                f"({datetime.now(timezone.utc).isoformat()[:19]})",
                flush=True,
            )
        else:
            print(f"[backfill] {report_date}: 入库失败", flush=True)
    print(json.dumps({"event": "backfill_done", "dates": dates}))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
