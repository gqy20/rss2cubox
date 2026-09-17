#!/usr/bin/env python
"""按网关真实单价核算 Agent 调用成本。

计价逻辑在 rss2cubox.token_pricing（移植自 manim-agent 并扩展了 new-api
quota 模式），本脚本只做日志分析。

为什么需要这个：claude_agent_sdk 报的 total_cost_usd 是 CLI 按它自己的 Claude
定价表算的。走第三方网关时那个金额与真实账单毫无关系 —— 实测一次完整运行
CLI 报 $324.17，按网关单价实际 ¥14.29，高估 166 倍。

用法:
    uv run python scripts/agent_cost.py                       # 分析最新一次运行日志
    uv run python scripts/agent_cost.py logs/cron/2026-09-16/*.log
    uv run python scripts/agent_cost.py --json                # 机器可读输出
    uv run python scripts/agent_cost.py --show-pricing        # 只看本地单价表
    uv run python scripts/agent_cost.py --refresh-pricing     # （唯一联网）从网关重拉单价并覆写 JSON
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

from rss2cubox import token_pricing as tp



def _load_env() -> None:
    """与项目其它模块一致：.env 覆盖已有环境变量。

    这里必须用覆盖而不是 setdefault：本机 shell profile 里导出着一套旧的
    bigmodel 凭据，如果用 setdefault 就会静默拿旧值去请求另一个网关。
    """
    env_file = ROOT_DIR / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ[key] = value.strip()


def refresh_pricing(path: Path = tp.PRICING_PATH) -> int:
    """唯一联网的命令：从网关重拉单价并覆写本地 JSON，保留原有注释与别名。"""
    import requests

    _load_env()
    base_url = os.getenv("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
    token = (os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not base_url or not token:
        print("需要 .env 里的 ANTHROPIC_BASE_URL 和 ANTHROPIC_AUTH_TOKEN", file=sys.stderr)
        return 2

    resp = requests.get(f"{base_url.rstrip('/')}/api/pricing", params={"key": token}, timeout=20)
    resp.raise_for_status()
    rows = resp.json().get("data", [])
    if not rows:
        print("网关返回了空的定价表，不覆写本地文件", file=sys.stderr)
        return 1

    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}

    models = {
        str(r["model_name"]): {
            "quota_type": r.get("quota_type", 0),
            "model_ratio": r.get("model_ratio", 0),
            "completion_ratio": r.get("completion_ratio", 0),
            "model_price": r.get("model_price", 0),
        }
        for r in rows
        if r.get("model_name")
    }

    meta = {
        "quota_per_unit": existing.get("quota_per_unit", 500000),
        "currency": existing.get("currency", "CNY"),
        "usd_exchange_rate": existing.get("usd_exchange_rate", 7.3),
        "quota_mode_defaults": existing.get("quota_mode_defaults", {"cache_read_ratio": 1.0, "cache_write_ratio": 1.0}),
    }
    try:
        status = requests.get(f"{base_url.rstrip('/')}/api/status", timeout=20).json().get("data", {})
        for src, dst in (("quota_per_unit", "quota_per_unit"),
                         ("usd_exchange_rate", "usd_exchange_rate"),
                         ("quota_display_type", "currency")):
            if status.get(src) is not None:
                meta[dst] = status[src]
    except Exception:  # noqa: BLE001
        pass

    out = {
        "_readme": existing.get("_readme", []),
        "gateway": base_url,
        **meta,
        "updated_at": __import__("datetime").date.today().isoformat(),
        "updated_from": "网关 /api/pricing 实拉",
        "aliases": existing.get("aliases", {}),
        "models": models,
    }
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tp.load_model_pricing.cache_clear()
    print(f"✓ 已刷新 {path.name}：{len(models)} 个模型（来自 {base_url}）")
    print(f"  换算：{meta['quota_per_unit']} quota = 1 {meta['currency']}，"
          f"1 USD = {meta['usd_exchange_rate']} {meta['currency']}")
    return 0


def analyze(paths: list[str], *, pricing: dict | None = None) -> dict:
    """解析 JSONL 日志里的 agent_sdk_result 事件，按模型聚合 token 与成本。"""
    data = pricing if pricing is not None else tp.load_model_pricing()
    per_model: dict[str, dict] = defaultdict(lambda: {
        "calls": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
        "cost": 0.0, "cli_cost_usd": 0.0,
    })
    events = 0
    missing_price: set[str] = set()

    for pattern in paths:
        for path in sorted(glob.glob(pattern)) or [pattern]:
            p = Path(path)
            if not p.exists():
                continue
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("event") != "agent_sdk_result":
                    continue
                events += 1
                model_usage = record.get("model_usage") or {}
                cli_cost = record.get("total_cost_usd") or 0.0

                if not model_usage:
                    usage_fallback = record.get("usage")
                    if usage_fallback:
                        model_usage = {"<unknown>": usage_fallback}
                    else:
                        model_usage = {}

                for model, usage in model_usage.items():
                    if not isinstance(usage, dict):
                        continue
                    bucket = per_model[model]
                    norm = tp.normalize_token_usage(usage)
                    bucket["calls"] += 1
                    bucket["input"] += norm["input_tokens"] or 0
                    bucket["output"] += norm["output_tokens"] or 0
                    bucket["cache_read"] += norm["cache_read_tokens"] or 0
                    bucket["cache_write"] += norm["cache_write_tokens"] or 0
                    bucket["cli_cost_usd"] += cli_cost

                    est = tp.estimate_token_cost(model, usage, pricing=data)
                    if est.get("note") == "pricing_not_found":
                        missing_price.add(model)
                    else:
                        bucket["cost"] += est.get("estimated_cost") or 0.0

    for bucket in per_model.values():
        bucket["cost_including_cache"] = bucket["cost"]

    return {
        "events": events,
        "currency": str(data.get("currency") or "CNY"),
        "usd_exchange_rate": float(data.get("usd_exchange_rate") or 0) or None,
        "models": dict(per_model),
        "missing_price": sorted(missing_price),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="按网关真实单价核算 Agent 成本")
    parser.add_argument("logs", nargs="*", help="JSONL 日志路径（默认取最新一次运行）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--show-pricing", action="store_true", help="只打印本地单价表")
    parser.add_argument("--refresh-pricing", action="store_true",
                        help="联网从网关重拉单价并覆写 model_pricing.json（唯一会联网的命令）")
    parser.add_argument("--pricing-file", default=str(tp.PRICING_PATH), help="单价表路径")
    args = parser.parse_args()

    if args.refresh_pricing:
        return refresh_pricing(Path(args.pricing_file))

    try:
        pricing = tp.load_model_pricing(args.pricing_file)
        if not pricing:
            raise FileNotFoundError
    except (FileNotFoundError, Exception):
        print("单价表不存在或为空，先执行: uv run python scripts/agent_cost.py --refresh-pricing",
              file=sys.stderr)
        return 2

    if args.show_pricing:
        cur = str(pricing.get("currency") or "CNY")
        qpu = float(pricing.get("quota_per_unit") or 500000)
        fx = float(pricing.get("usd_exchange_rate") or 7.3)
        print(f"单价表 {args.pricing_file}  (更新于 {pricing.get('updated_at','?')}，"
              f"来源 {pricing.get('gateway','?')})")
        print(f"换算：{qpu:.0f} quota = 1 {cur}，1 USD = {fx} {cur}")
        cache = pricing.get("quota_mode_defaults") or {}
        print(f"cache_read_ratio={cache.get('cache_read_ratio','?')}  "
              f"cache_write_ratio={cache.get('cache_write_ratio','?')}"
              f"  （1.0 = 按 input 同价，成本上界）\n")
        hdr = (f"{'模型':28s} {'ratio':>8s} {'compl':>7s} "
               f"{f'输入{cur}/M':>11s} {f'输出{cur}/M':>11s} {'cache_read/M':>12s} {'输入$/M':>10s} {'输出$/M':>10s}")
        print(hdr)
        print("-" * 104)
        for name, entry in sorted((pricing.get("models") or {}).items()):
            rates = tp._entry_to_rates(entry, pricing)
            if not rates:
                continue
            def _fmt(v):
                return f"{v:.4f}" if isinstance(v, (int, float)) else "-"
            print(f"{name:28s} {entry.get('model_ratio','-'):>8} {entry.get('completion_ratio','-'):>7} "
                  f"{_fmt(rates['input']):>11s} {_fmt(rates['output']):>11s} "
                  f"{_fmt(rates['cache_read']):>12s} "
                  f"{_fmt(rates['input']/fx if fx else None):>10s} "
                  f"{_fmt(rates['output']/fx if fx else None):>10s}")
        return 0

    paths = args.logs
    if not paths:
        candidates = sorted(glob.glob(str(ROOT_DIR / "logs" / "**" / "*.log"), recursive=True),
                            key=os.path.getmtime)
        jsonl = sorted(glob.glob(str(ROOT_DIR / "logs" / "**" / "*.jsonl"), recursive=True),
                       key=os.path.getmtime)
        paths = (candidates + jsonl)[-1:]
        if not paths:
            print("找不到日志，先跑一次 make run / make policy", file=sys.stderr)
            return 1
        print(f"（未指定日志，使用最新的: {paths[0]}）")

    report = analyze(paths, pricing=pricing)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0

    cur = report["currency"]
    fx = report["usd_exchange_rate"]
    print(f"\n日志: {', '.join(paths)}")
    print(f"agent_sdk_result 事件数: {report['events']}")
    if report["missing_price"]:
        print(f"⚠ 定价表里没有这些模型，其用量未被计价: {report['missing_price']}")

    total = total_usd = total_cli = 0.0
    total_in = total_out = total_cr = 0
    print()
    hdr = (f"{'模型':26s} {'调用':>5s} {'输入tok':>11s} {'cache读':>10s} {'输出tok':>9s} "
           f"{f'真实({cur})':>11s} {'真实($)':>10s} {'CLI报($)':>10s} {'高估':>7s}")
    print(hdr)
    print("-" * 116)
    for model, b in sorted(report["models"].items(), key=lambda x: -x[1]["cost"]):
        over = (b["cli_cost_usd"] / (b["cost"] / fx)) if fx and b["cost"] > 0 else 0.0
        print(f"{model:26s} {b['calls']:>5d} {b['input']:>11,d} {b['cache_read']:>10,d} {b['output']:>9,d} "
              f"{b['cost']:>11.4f} {b['cost']/fx if fx else 0:>10.4f} {b['cli_cost_usd']:>10.4f} "
              f"{over:>6.0f}x")
        total += b["cost"]
        total_usd += (b["cost"] / fx) if fx else 0
        total_cli += b["cli_cost_usd"]
        total_in += b["input"]
        total_out += b["output"]
        total_cr += b["cache_read"]

    print("-" * 116)
    calls = sum(b["calls"] for b in report["models"].values())
    over = (total_cli / total_usd) if total_usd > 0 else 0.0
    print(f"{'合计':26s} {calls:>5d} {int(total_in):>11,d} {int(total_cr):>10,d} {int(total_out):>9,d} "
          f"{total:>11.4f} {total_usd:>10.4f} {total_cli:>10.4f} {over:>6.0f}x")

    if total_cr > 0:
        # 按 cache_read 同价估算 cache 部分占的成本（成本上界）
        cache_cost = sum(
            b["cache_read"] * (tp._entry_to_rates(pricing["models"].get(m, {}), pricing) or {}).get("cache_read") or 0
            for m, b in report["models"].items()
        ) / 1_000_000
        print(f"\n  其中 cache_read 部分约 ¥{cache_cost:.4f} —— 如果网关对 cache 打折，"
              f"实际会低于此值（cache_read_ratio 在 model_pricing.json 的 quota_mode_defaults 里调）")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
