#!/usr/bin/env python3
"""一次性迁移脚本：将本地文件数据批量导入 Neon 数据库。

迁移内容：
  state.json                         → sent_items / ai_results / feed_cursors / feed_failures
  run_events.jsonl                   → run_events
  web/public/data/updates_history.jsonl → run_events（历史记录）
  web/public/data/global_insights.json  → global_insights
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rss2cubox.db import save_global_insights, save_run_events, save_state

STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
RUN_EVENTS_FILE = Path(os.getenv("RUN_EVENTS_FILE", "run_events.jsonl"))
HISTORY_FILE = Path(os.getenv("WEB_HISTORY_FILE", "web/public/data/updates_history.jsonl"))
INSIGHTS_FILE = Path(os.getenv("WEB_INSIGHTS_FILE", "web/public/data/global_insights.json"))
NEON_DATABASE_URL = os.getenv("NEON_DATABASE_URL", "").strip()


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if raw:
                try:
                    rows.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass
    return rows


def main() -> None:
    if not NEON_DATABASE_URL:
        print("ERROR: NEON_DATABASE_URL 未设置", flush=True)
        sys.exit(1)

    # 1. state.json → 4 张状态表
    if STATE_FILE.exists():
        with STATE_FILE.open("r", encoding="utf-8") as f:
            state = json.load(f)
        sent = state.get("sent", {})
        ai = state.get("ai", {})
        fc = state.get("feed_cursor", {})
        ff = state.get("feed_failures", {})
        print(f"[state] sent={len(sent)}, ai={len(ai)}, feed_cursor={len(fc)}, feed_failures={len(ff)}")
        save_state(NEON_DATABASE_URL, state)
        print("[state] ✓ 写入完成")

    # 2. run_events.jsonl + updates_history.jsonl → run_events 表
    current_events = load_jsonl(RUN_EVENTS_FILE)
    history_events = load_jsonl(HISTORY_FILE)
    all_events = current_events + history_events
    print(f"[run_events] current={len(current_events)}, history={len(history_events)}, total={len(all_events)}")
    if all_events:
        save_run_events(NEON_DATABASE_URL, all_events)
        print("[run_events] ✓ 写入完成")

    # 3. global_insights.json → global_insights 表
    if INSIGHTS_FILE.exists():
        with INSIGHTS_FILE.open("r", encoding="utf-8") as f:
            insights = json.load(f)
        print(f"[global_insights] generated_at={insights.get('generated_at')}")
        save_global_insights(NEON_DATABASE_URL, insights)
        print("[global_insights] ✓ 写入完成")

    print("\n全部迁移完成！", flush=True)


if __name__ == "__main__":
    main()

