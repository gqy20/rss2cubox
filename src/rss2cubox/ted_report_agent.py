"""Generate an unpublished TED report through the same API as the editor.

Run: uv run python -m rss2cubox.ted_report_agent --start 2026-09-12 --end 2026-09-18
The frontend must be running. This command never publishes or edits an existing issue.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import anyio
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def build_report(draft: dict[str, Any], packet: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Resolve model citations exclusively against the supplied material snapshot.

    No model-provided URL, publisher, publication date, coverage count or host note is accepted.
    The API performs the final shared editorial contract validation before saving.
    """
    catalog = {f"{s['kind']}:{s['id']}": s for s in packet["materials"]}
    report = copy.deepcopy(draft)
    if not isinstance(result.get("topics"), list) or not 1 <= len(result["topics"]) <= 10:
        raise ValueError("生成结果需要 1–10 个有证据的议题。")
    topics = []
    for topic in result["topics"]:
        sources = []
        keys: set[str] = set()
        for ref in topic.get("sources", []):
            key = ref.get("key")
            if key not in catalog or key in keys:
                raise ValueError("生成结果引用了不存在或重复的素材。")
            reason = ref.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("生成结果缺少引用理由。")
            keys.add(key)
            sources.append({**catalog[key], "reason": reason.strip()})
        if not sources:
            raise ValueError("生成结果包含无来源议题。")
        fields = {}
        for name in ("title", "claim", "body", "uncertainty", "watch"):
            value = topic.get(name)
            if not isinstance(value, str):
                raise ValueError(f"生成结果缺少 {name}。")
            if name in ("title", "claim") and not value.strip():
                raise ValueError("生成结果缺少议题标题或判断。")
            for citation in re.findall(r"\[(\d+)\](?!\()", value):
                if not 1 <= int(citation) <= len(sources):
                    raise ValueError("生成结果的引用编号与资料不对应。")
            fields[name] = value.strip()
        topics.append({**fields, "id": str(uuid.uuid4()), "sources": sources, "host_notes": "", "image": None})
    for name in ("title", "intro"):
        if not isinstance(result.get(name), str):
            raise ValueError(f"生成结果缺少 {name}。")
        report[name] = result[name].strip()
    if not isinstance(result.get("tags"), list) or any(not isinstance(tag, str) for tag in result["tags"]):
        raise ValueError("主题标签格式不正确。")
    report.update(topics=topics, tags=result["tags"], next_watch="", preparation="edited",
                  generation={"method": "agent", "generated_at": datetime.now(timezone.utc).isoformat()})
    return report


async def generate(packet: dict[str, Any], max_budget_usd: float) -> dict[str, Any]:
    from rss2cubox.agent_sdk_runner import (
        cleanup_temp_files, create_read_webpage_mcp, run_json_agent, write_temp_json,
    )
    from rss2cubox.prompt_registry import get

    config = get("ted_report")
    materials = [{**item, "key": f"{item['kind']}:{item['id']}"} for item in packet["materials"]]
    filename = write_temp_json({**packet, "materials": materials})
    try:
        server, tool_name = create_read_webpage_mcp("ted-report-tools")
        return await run_json_agent(
            prompt=(f"请通读 {filename}，综合生成 {packet['start_date']} 至 {packet['end_date']} 的他山 TED 草稿。"
                    f"候选资料共 {len(materials)} 条，覆盖统计与候选选入数量不是同一个口径。"
                    "资料的 key 是唯一可引用的标识。核对关键原文后输出 JSON。"),
            system_prompt=config.system_prompt,
            schema=config.output_schema,
            allowed_tools=["Read", tool_name],
            mcp_servers={"ted-report-tools": server},
            setting_sources=None,
            max_turns=config.params.get("max_turns", 40),
            timeout_seconds=config.params.get("timeout_seconds", 900),
            max_budget_usd=max_budget_usd,
            cwd=ROOT,
        )
    finally:
        cleanup_temp_files(filename)


def _response(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("前端未返回 JSON，请检查 --base-url 和前端服务。") from exc
    if not response.ok:
        raise RuntimeError(payload.get("error", f"请求失败（HTTP {response.status_code}）"))
    return payload


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    load_dotenv(ROOT / "web" / ".env.local", override=False)
    yesterday = datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)
    parser = argparse.ArgumentParser(description="他山 TED 综合初稿生成，只保存草稿，不发布。")
    parser.add_argument("--start", default=(yesterday - timedelta(days=6)).isoformat())
    parser.add_argument("--end", default=yesterday.isoformat())
    parser.add_argument("--base-url", default="http://localhost:3424")
    parser.add_argument("--max-budget-usd", type=float, default=5.0)
    parser.add_argument("--dry-run", action="store_true", help="读取素材并展示覆盖情况，不创建草稿、不调用模型")
    args = parser.parse_args()
    try:
        days = (date.fromisoformat(args.end) - date.fromisoformat(args.start)).days + 1
        if not 1 <= days <= 31 or not 0 < args.max_budget_usd <= 50:
            raise ValueError("日期范围应为 1–31 天，模型预算应大于 0 且不超过 50 美元。")
        base = args.base_url.rstrip("/")
        parsed = urlparse(base)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("--base-url 必须是前端的 http(s) 地址。")
        if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("远程前端请使用 HTTPS。")
        session = requests.Session()
        session.headers["Origin"] = f"{parsed.scheme}://{parsed.netloc}"
        packet = _response(session.get(f"{base}/api/ted/materials", params={"start": args.start, "end": args.end}, timeout=30))["data"]
        print(json.dumps({"覆盖日期": [args.start, args.end], "统计": packet["coverage"], "候选资料": len(packet["materials"])}, ensure_ascii=False))
        if args.dry_run:
            return 0
        if not packet["materials"]:
            raise ValueError("没有可用于综合的已分析素材。请选择有数据的区间。")
        token = os.environ.get("TED_WRITE_TOKEN", "")
        if len(token) < 32:
            raise ValueError("后台生成需要配置 TED_WRITE_TOKEN（至少32字符），观众阅读不需要此配置。")
        session.headers["Authorization"] = f"Bearer {token}"
        issue = _response(session.post(f"{base}/api/ted", json={"start": args.start, "end": args.end}, timeout=30))["data"]
        print("已创建本期素材快照，正在生成报告。")
        packet = _response(session.get(f"{base}/api/ted/materials", params={
            "start": args.start, "end": args.end, "cutoff": issue["report"]["cutoff_at"],
        }, timeout=30))["data"]
        report = build_report(issue["report"], packet, anyio.run(generate, packet, args.max_budget_usd))
        _response(session.patch(f"{base}/api/ted/{issue['id']}", json={
            "version": issue["version"], "action": "save", "report": report,
        }, timeout=30))
        print(f"报告已保存，阅读链接：{base}/ted/{issue['id']}")
        return 0
    except (ValueError, RuntimeError, requests.RequestException) as exc:
        # Do not print HTTP request objects or configuration, which can carry credentials.
        print(f"TED 初稿未完成：{type(exc).__name__ if isinstance(exc, requests.RequestException) else exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
