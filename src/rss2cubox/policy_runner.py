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
from rss2cubox.policy.enrich_agent import enrich_policy_documents  # noqa: E402
from rss2cubox.policy.triage_agent import triage_policy_documents  # noqa: E402
from rss2cubox.policy.store import (  # noqa: E402
    count_policy_documents,
    count_policy_triage,
    ensure_policy_schema,
    get_documents_for_enrichment,
    get_source_states,
    get_stale_sources,
    get_untriaged_documents,
    record_source_state,
    save_policy_documents,
    save_policy_enrichment,
    save_triage_results,
)

POLICY_SOURCES_FILE = Path(os.getenv("POLICY_SOURCES_FILE", str(ROOT_DIR / "policy_sources.toml")))
POLICY_FETCH_CONCURRENCY = max(1, int(os.getenv("POLICY_FETCH_CONCURRENCY", "4")))
POLICY_CONNECT_TIMEOUT_SECONDS = float(os.getenv("POLICY_CONNECT_TIMEOUT_SECONDS", "5"))
POLICY_READ_TIMEOUT_SECONDS = float(os.getenv("POLICY_READ_TIMEOUT_SECONDS", "20"))
# 连续空跑达到这个次数就告警（政府站点更新频率低，2 次比较稳妥）
POLICY_STALE_EMPTY_RUNS = max(1, int(os.getenv("POLICY_STALE_EMPTY_RUNS", "2")))
POLICY_ENRICH_LIMIT = max(1, int(os.getenv("POLICY_ENRICH_LIMIT", "20")))
POLICY_TRIAGE_LIMIT = max(1, int(os.getenv("POLICY_TRIAGE_LIMIT", "300")))
# enrich 门槛与 triage_agent 的统计阈值必须同源：env > prompts/policy_enrich.yaml > 代码默认。
# 此前这里只读 env（默认 3），yaml 降到 2 后 cron 仍按 3 跑，两处口径分叉。
from rss2cubox.prompt_registry import param as _param

POLICY_ENRICH_MIN_RELEVANCE = min(
    5,
    max(1, int(_param("policy_enrich", "min_relevance", 3, env_var="POLICY_ENRICH_MIN_RELEVANCE"))),
)


def _run_triage_stage(
    *,
    limit: int,
    site_key: str | None,
    level: str | None,
    stats: dict[str, Any],
) -> None:
    """廉价预筛：一次调用批量给标题打分，只让高相关的进入逐篇 deep enrich。"""
    docs = get_untriaged_documents(limit=limit, site_key=site_key, level=level)
    if not docs:
        log_event("INFO", "policy_triage_skipped", stage="policy_triage", reason="nothing_untriaged")
        stats["triage_input"] = 0
        return

    flushed_ids: set[str] = set()

    def _flush(rows: list[dict[str, Any]]) -> None:
        save_triage_results(rows)
        flushed_ids.update(str(r.get("id", "")) for r in rows)

    outcome = triage_policy_documents(docs, log_event=log_event, on_batch_done=_flush)
    # 兵底：回调未触发或抛异常的那部分补写一次（save_triage_results 是幂等 UPDATE）
    remaining = [r for r in outcome["results"] if str(r.get("id", "")) not in flushed_ids]
    saved = len(flushed_ids) + save_triage_results(remaining)
    stats.update({f"triage_{k}": v for k, v in outcome["stats"].items()})
    stats["triage_saved"] = saved
    stats["triage_flushed_incrementally"] = len(flushed_ids)


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


def _run_enrich_stage(
    *,
    limit: int,
    site_key: str | None,
    level: str | None,
    fetch_full_text: bool,
    min_triage_relevance: int | None,
    stats: dict[str, Any],
) -> None:
    """对尚未 enrich 的政策文件做结构化抽取并回写。"""
    docs = get_documents_for_enrichment(
        limit=limit,
        site_key=site_key,
        level=level,
        min_triage_relevance=min_triage_relevance,
    )
    if not docs:
        log_event(
            "INFO",
            "policy_enrich_skipped",
            stage="policy_enrich",
            reason="no_unenriched_documents",
            min_triage_relevance=min_triage_relevance,
        )
        stats["enrich_total"] = 0
        return

    outcome = enrich_policy_documents(
        docs,
        fetch_full_text_enabled=fetch_full_text,
        log_event=log_event,
    )
    full_texts = outcome.get("full_texts", {})
    saved = 0
    failures: list[dict[str, str]] = []
    save_failures: list[str] = []
    for doc_id, (enriched, reason) in outcome["results"].items():
        if not enriched:
            failures.append({"doc_id": doc_id, "reason": reason})
            continue
        if save_policy_enrichment(doc_id, enriched, full_text=full_texts.get(doc_id)):
            saved += 1
        else:
            # agent 成功但写库失败 —— 不报出来的话只会表现为两个数字对不上
            save_failures.append(doc_id)
            if log_event:
                log_event("WARN", "policy_enrich_save_failed", stage="policy_enrich", doc_id=doc_id)

    inner = outcome["stats"]
    stats.update(
        enrich_total=inner["total"],
        enrich_succeeded=inner["succeeded"],
        enrich_failed=inner["failed"],
        enrich_fulltext=inner["fulltext"],
        enrich_saved=saved,
    )
    if save_failures:
        stats["enrich_save_failures"] = save_failures
    if failures:
        stats["enrich_failures"] = failures[:10]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="抓取政策信源列表页并入库")
    parser.add_argument("--only", default="", help="只抓这些 key，逗号分隔")
    parser.add_argument("--level", default="", help="只抓这些级别: national,province,city")
    parser.add_argument("--sources", default=str(POLICY_SOURCES_FILE), help="配置文件路径")
    parser.add_argument("--include-disabled", action="store_true", help="包含 enabled=false 的站点")
    parser.add_argument("--dry-run", action="store_true", help="只抓取和解析，不写数据库")
    parser.add_argument("--status", action="store_true", help="只打印信源健康度后退出")
    parser.add_argument("--enrich", action="store_true", help="抓取后对新增文件做结构化抽取")
    parser.add_argument("--enrich-only", action="store_true", help="跳过抓取，只补做 enrich（回填空数据用）")
    parser.add_argument("--enrich-limit", type=int, default=POLICY_ENRICH_LIMIT, help="本次最多 enrich 多少篇")
    parser.add_argument("--no-fulltext", action="store_true", help="不抓详情页正文，只用标题抽取（便宜但质量低）")
    parser.add_argument("--triage", action="store_true", help="只跑预筛（标题批量分类），不做 deep enrich")
    parser.add_argument("--triage-limit", type=int, default=POLICY_TRIAGE_LIMIT, help="本次最多预筛多少篇")
    parser.add_argument(
        "--no-triage",
        action="store_true",
        help="enrich 前不跑预筛（会对所有未 enrich 文档逐篇调用，贵）",
    )
    parser.add_argument(
        "--enrich-min-relevance",
        type=int,
        default=POLICY_ENRICH_MIN_RELEVANCE,
        help=f"只对预筛 AI 相关度 ≥ 此值的文档做 deep enrich（默认 {POLICY_ENRICH_MIN_RELEVANCE}，1=不设门槛）",
    )
    args = parser.parse_args(argv)

    if args.status:
        return _print_status()

    min_relevance = args.enrich_min_relevance if args.enrich_min_relevance > 1 else None

    if args.enrich_only or args.triage:
        if not ensure_policy_schema():
            print("建表失败：检查 DATABASE_URL（make db）", file=sys.stderr)
            return 1
        stats: dict[str, Any] = {"sites": 0, "sites_ok": 0, "sites_failed": 0, "items_total": 0}
        only_keys = {k.strip() for k in args.only.split(",") if k.strip()}
        single_key = next(iter(only_keys)) if len(only_keys) == 1 else None
        level_filter = args.level.strip() or None
        started = datetime.now(timezone.utc)

        if args.triage:
            _run_triage_stage(limit=args.triage_limit, site_key=single_key, level=level_filter, stats=stats)
        if args.enrich_only:
            _run_enrich_stage(
                limit=args.enrich_limit,
                site_key=single_key,
                level=level_filter,
                fetch_full_text=not args.no_fulltext,
                min_triage_relevance=min_relevance,
                stats=stats,
            )

        stats["duration_s"] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
        stats["documents"] = count_policy_documents()
        stats["triage_distribution"] = count_policy_triage()
        log_event("INFO", "policy_run_summary", stage="summary", **stats)

        print()
        if "triage_saved" in stats:
            print(
                f"预筛：{stats.get('triage_saved', 0)}/{stats.get('triage_input', 0)} 篇已打分"
                f"（其中政策文件 {stats.get('triage_policy', 0)} 篇，"
                f"相关度≥{stats.get('triage_threshold', '?')} 的 {stats.get('triage_relevant', 0)} 篇）"
            )
        if "enrich_saved" in stats:
            print(
                f"enrich：成功 {stats.get('enrich_saved', 0)}/{stats.get('enrich_total', 0)} 篇"
                f"（带正文 {stats.get('enrich_fulltext', 0)} 篇）"
            )
        print(f"耗时 {stats['duration_s']}s；库内累计 {stats['documents']}")
        print(f"预筛分布 {stats['triage_distribution']}")
        return 0

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
        log_event("WARN", "policy_no_sites_selected", only=args.only, level_filter=args.level)
        print("没有匹配的站点。检查 --only / --level 过滤条件，或配置文件里 enabled 是否为 false。")
        return 0

    if not args.dry_run and not ensure_policy_schema():
        log_event("ERROR", "policy_schema_failed")
        print("建表失败：检查 DATABASE_URL 是否正确、PostgreSQL 是否在跑（make db）", file=sys.stderr)
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

        if args.enrich:
            # enrich 默认先跑预筛：否则停水通知、月票提示会和真正的法规文件
            # 消耗同等的 deep enrich 预算（实测 ~$0.14/篇）
            if not args.no_triage:
                _run_triage_stage(
                    limit=args.triage_limit,
                    site_key=None,
                    level=(args.level.strip() or None),
                    stats=stats,
                )
            _run_enrich_stage(
                limit=args.enrich_limit,
                site_key=None,
                level=(args.level.strip() or None),
                fetch_full_text=not args.no_fulltext,
                min_triage_relevance=min_relevance,
                stats=stats,
            )
            stats["documents"] = count_policy_documents()

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
    if args.enrich and not args.dry_run:
        print(
            f"enrich：成功 {stats.get('enrich_saved', 0)}/{stats.get('enrich_total', 0)} 篇"
            f"（带正文 {stats.get('enrich_fulltext', 0)} 篇）；库内累计 {stats.get('documents')}"
        )
    if stats["failed_sites"]:
        print("失败站点:")
        for failed in stats["failed_sites"]:
            print(f"    {failed['key']:22s} {failed['status']:13s} {failed['error'][:70]}")
    return 0 if stats["sites_ok"] > 0 or args.dry_run else 1


if __name__ == "__main__":
    raise SystemExit(main())
