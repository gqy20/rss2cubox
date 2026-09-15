"""政策信源抓取入口。

用法:
    uv run python -m rss2cubox.policy_runner
    uv run python -m rss2cubox.policy_runner --only beijing_zhengce,tc260_zqyj
    uv run python -m rss2cubox.policy_runner --level province,city
    uv run python -m rss2cubox.policy_runner --include-disabled   # 连 playwright 站点一起试
    uv run python -m rss2cubox.policy_runner --dry-run            # 只抓不入库
    uv run python -m rss2cubox.policy_runner --status             # 只看信源健康度

与主链路 runner.py 分开，因为两者的抓取语义不同（RSS feed vs HTML 列表页），
打分标尺也不同（科技媒体视角 vs 法规监管视角）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def _load_env() -> None:
    """与项目其它模块一致：.env 覆盖已有环境变量。"""
    load_dotenv(ROOT_DIR / ".env", override=True)


_load_env()

from rss2cubox.policy.config import load_sources  # noqa: E402
from rss2cubox.policy.engine import scrape_all  # noqa: E402
from rss2cubox.policy.store import (  # noqa: E402
    ensure_policy_schema,
    get_source_states,
    get_stale_sources,
    record_source_state,
    save_policy_documents,
)

POLICY_SOURCES_FILE = Path(os.getenv("POLICY_SOURCES_FILE", str(ROOT_DIR / "policy_sources.toml")))
POLICY_FETCH_CONCURRENCY = max(1, int(os.getenv("POLICY_FETCH_CONCURRENCY", "4")))
POLICY_CONNECT_TIMEOUT_SECONDS = float(os.getenv("POLICY_CONNECT_TIMEOUT_SECONDS", "5"))
POLICY_READ_TIMEOUT_SECONDS = float(os.getenv("POLICY_READ_TIMEOUT_SECONDS", "20"))
# 连续空跑达到这个次数就告警（政府站点更新频率低，2 次比较稳妥）
POLICY_STALE_EMPTY_RUNS = max(1, int(os.getenv("POLICY_STALE_EMPTY_RUNS", "2")))

_RUN_ID = os.getenv("RSS2CUBOX_RUN_ID") or f"policy-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def log_event(level: str, event: str, **fields: Any) -> None:
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "event": event,
        "run_id": _RUN_ID,
    }
    payload.update(fields)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str), flush=True)


def _print_status() -> int:
    states = get_source_states()
    if not states:
        print("还没有任何抓取记录，先跑一次: uv run python -m rss2cubox.policy_runner")
        return 0
    stale = {row["site_key"] for row in get_stale_sources(min_empty_runs=POLICY_STALE_EMPTY_RUNS)}
    print(f"\n{'站点':22s} {'级别':9s} {'地区':6s} {'状态':13s} {'条数':>5s} {'空跑':>4s}  最后成功")
    print("─" * 92)
    for row in states:
        flag = "⚠ " if row["site_key"] in stale else "  "
        last_ok = row.get("last_success_at")
        last_ok_s = last_ok.strftime("%Y-%m-%d %H:%M") if last_ok else "从未"
        print(
            f"{flag}{(row['site_key'] or ''):20s} {(row.get('level') or ''):9s} "
            f"{(row.get('region') or ''):6s} {(row.get('last_status') or ''):13s} "
            f"{row.get('last_item_count') or 0:>5d} {row.get('consecutive_empty_runs') or 0:>4d}  {last_ok_s}"
        )
    if stale:
        print(f"\n⚠ {len(stale)} 个站点连续空跑 ≥{POLICY_STALE_EMPTY_RUNS} 次，疑似已失效（改版/被拦）:")
        for row in states:
            if row["site_key"] in stale:
                print(f"    {row['site_key']:22s} {(row.get('last_error') or '')[:70]}")
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="抓取政策信源列表页并入库")
    parser.add_argument("--only", default="", help="只抓这些 key，逗号分隔")
    parser.add_argument("--level", default="", help="只抓这些级别: national,province,city")
    parser.add_argument("--sources", default=str(POLICY_SOURCES_FILE), help="配置文件路径")
    parser.add_argument("--include-disabled", action="store_true", help="包含 enabled=false 的站点")
    parser.add_argument("--dry-run", action="store_true", help="只抓取和解析，不写数据库")
    parser.add_argument("--status", action="store_true", help="只打印信源健康度后退出")
    args = parser.parse_args(argv)

    if args.status:
        return _print_status()

    only_keys = {k.strip() for k in args.only.split(",") if k.strip()} or None
    only_levels = {k.strip().lower() for k in args.level.split(",") if k.strip()} or None

    try:
        sites = load_sources(
            args.sources,
            include_disabled=args.include_disabled,
            only_levels=only_levels,
            only_keys=only_keys,
        )
    except (FileNotFoundError, ValueError) as exc:
        log_event("ERROR", "policy_config_invalid", error=str(exc))
        return 2

    if not sites:
        log_event("WARN", "policy_no_sites_selected", only=args.only, level=args.level)
        print("没有匹配的站点。检查 --only / --level 过滤条件，或配置文件里 enabled 是否为 false。")
        return 0

    if not args.dry_run and not ensure_policy_schema():
        log_event("ERROR", "policy_schema_failed")
        print("建表失败：检查 LOCAL_DB_URL 是否正确、PostgreSQL 是否在跑（make db）", file=sys.stderr)
        return 1

    log_event(
        "INFO",
        "policy_run_start",
        stage="policy_fetch",
        sites=len(sites),
        site_keys=[s.key for s in sites],
        concurrency=POLICY_FETCH_CONCURRENCY,
        dry_run=args.dry_run,
    )

    started = datetime.now(timezone.utc)
    results = scrape_all(
        sites,
        concurrency=POLICY_FETCH_CONCURRENCY,
        connect_timeout=POLICY_CONNECT_TIMEOUT_SECONDS,
        read_timeout=POLICY_READ_TIMEOUT_SECONDS,
        log_event=log_event,
    )
    site_by_key = {s.key: s for s in sites}

    stats: dict[str, Any] = {
        "sites": len(sites),
        "sites_ok": 0,
        "sites_failed": 0,
        "items_total": 0,
        "inserted": 0,
        "updated": 0,
        "by_level": {},
        "failed_sites": [],
    }

    for result in results:
        site = site_by_key.get(result.site_key)
        level = site.level if site else ""
        region = site.region if site else ""
        if result.ok:
            stats["sites_ok"] += 1
        else:
            stats["sites_failed"] += 1
            stats["failed_sites"].append({"key": result.site_key, "status": result.status, "error": result.error})
        stats["items_total"] += len(result.items)
        stats["by_level"][level] = stats["by_level"].get(level, 0) + len(result.items)

        if args.dry_run:
            continue
        record_source_state(result, level=level, region=region)
        if result.items:
            saved = save_policy_documents(
                result.items,
                site_name=result.site_name,
                level=level,
                region=region,
            )
            stats["inserted"] += saved["inserted"]
            stats["updated"] += saved["updated"]

    if not args.dry_run:
        stale = get_stale_sources(min_empty_runs=POLICY_STALE_EMPTY_RUNS)
        if stale:
            log_event(
                "WARN",
                "policy_sources_stale",
                stage="policy_fetch",
                threshold=POLICY_STALE_EMPTY_RUNS,
                count=len(stale),
                sites=[
                    {
                        "key": row["site_key"],
                        "empty_runs": row["consecutive_empty_runs"],
                        "status": row["last_status"],
                        "error": (row.get("last_error") or "")[:120],
                    }
                    for row in stale
                ],
            )
            stats["stale_sites"] = [row["site_key"] for row in stale]

    stats["duration_s"] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
    log_event("INFO", "policy_run_summary", stage="summary", **stats)

    print(
        f"\n政策抓取完成：{stats['sites_ok']}/{stats['sites']} 个站点成功，"
        f"共 {stats['items_total']} 条"
        + (f"（新增 {stats['inserted']}，复见 {stats['updated']}）" if not args.dry_run else "（dry-run 未入库）")
        + f"，耗时 {stats['duration_s']}s"
    )
    if stats.get("stale_sites"):
        print(f"⚠ 疑似失效站点: {', '.join(stats['stale_sites'])} —— 用 --status 查看详情")
    if stats["failed_sites"]:
        print("失败站点:")
        for failed in stats["failed_sites"]:
            print(f"    {failed['key']:22s} {failed['status']:13s} {failed['error'][:70]}")
    return 0 if stats["sites_ok"] > 0 or args.dry_run else 1


if __name__ == "__main__":
    raise SystemExit(main())
