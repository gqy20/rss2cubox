#!/usr/bin/env python3
"""审计 ic 中 gqy 数据质量，输出汇总和低质量样本。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests


def load_local_env_file(env_file: Path = Path(".env")) -> None:
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, value.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("IC_API_URL", "").strip())
    parser.add_argument("--source-type", default=os.getenv("IC_SOURCE_TYPE", "gqy").strip() or "gqy")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--example-limit", type=int, default=20)
    parser.add_argument("--output", default="", help="可选，导出审计结果 JSON 文件")
    return parser.parse_args()


def fetch_articles(base_url: str, source_type: str, page_size: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        response = requests.get(
            f"{base_url}?limit={page_size}&offset={offset}&source_type={source_type}",
            timeout=30,
        )
        response.raise_for_status()
        items = response.json().get("data", {}).get("list", [])
        if not isinstance(items, list):
            break
        rows.extend(item for item in items if isinstance(item, dict))
        if len(items) < page_size:
            break
        offset += page_size
    return rows


def is_empty_text(value: Any) -> bool:
    return value is None or not str(value).strip()


def analyze(rows: list[dict[str, Any]], example_limit: int) -> dict[str, Any]:
    summary = {
        "total": len(rows),
        "description_empty": 0,
        "reason_empty": 0,
        "actionable_empty": 0,
        "hidden_signal_empty": 0,
        "tags_empty": 0,
        "all_analysis_empty": 0,
    }
    examples: list[dict[str, Any]] = []

    for item in rows:
        description_empty = is_empty_text(item.get("description"))
        reason_empty = is_empty_text(item.get("reason"))
        actionable_empty = is_empty_text(item.get("actionable"))
        hidden_signal_empty = is_empty_text(item.get("hidden_signal"))
        tags_empty = not isinstance(item.get("tags"), list) or len(item.get("tags", [])) == 0

        summary["description_empty"] += int(description_empty)
        summary["reason_empty"] += int(reason_empty)
        summary["actionable_empty"] += int(actionable_empty)
        summary["hidden_signal_empty"] += int(hidden_signal_empty)
        summary["tags_empty"] += int(tags_empty)
        if reason_empty and actionable_empty and hidden_signal_empty:
            summary["all_analysis_empty"] += 1

        if len(examples) < example_limit and (
            description_empty
            or reason_empty
            or actionable_empty
            or hidden_signal_empty
            or tags_empty
        ):
            examples.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "tags": item.get("tags"),
                    "description": item.get("description"),
                    "reason": item.get("reason"),
                    "actionable": item.get("actionable"),
                    "hidden_signal": item.get("hidden_signal"),
                    "url": item.get("url"),
                }
            )

    return {"summary": summary, "examples": examples}


def main() -> None:
    load_local_env_file()
    args = parse_args()
    if not args.api_url:
        print("ERROR: --api-url 或 IC_API_URL 未设置", file=sys.stderr, flush=True)
        sys.exit(1)

    base_url = args.api_url.rsplit("/batch", 1)[0]
    rows = fetch_articles(base_url, args.source_type, args.page_size)
    report = analyze(rows, args.example_limit)

    payload = {
        "source_type": args.source_type,
        "base_url": base_url,
        "summary": report["summary"],
        "examples": report["examples"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
