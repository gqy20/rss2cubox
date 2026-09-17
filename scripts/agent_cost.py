#!/usr/bin/env python
"""按网关真实单价核算 Agent 调用成本。

为什么需要这个：claude_agent_sdk 报的 total_cost_usd 是 CLI 按它自己的 Claude
定价表算的。走第三方网关（new-api）时那个金额与真实账单毫无关系——实测一个
38K input / 51 output 的调用，CLI 报 $0.115，按网关单价实际约 ¥0.005，
高估约 150 倍。

单价来源：**本地 model_pricing.json**，默认不联网。价格很少变动，本地维护
比每次去拉网关更简单也更可靠（不受网关鉴权方式变化影响，且可进版本库 review）。

真实成本的算法（new-api 约定）：
    quota   = input_tokens × model_ratio
            + output_tokens × model_ratio × completion_ratio
    金额    = quota / quota_per_unit        （单位见 JSON 里的 currency）
    美元    = 金额 / usd_exchange_rate

用法:
    uv run python scripts/agent_cost.py                       # 分析最新一次运行日志
    uv run python scripts/agent_cost.py logs/cron/2026-09-16/*.log
    uv run python scripts/agent_cost.py --json                # 机器可读输出
    uv run python scripts/agent_cost.py --show-pricing        # 只看本地单价表
    uv run python scripts/agent_cost.py --refresh-pricing     # （唯一联网的命令）从网关重拉单价并覆写 JSON
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


def _load_env() -> None:
    """与项目其它模块一致：.env 覆盖已有环境变量。

    这里必须用覆盖而不是 setdefault：本机 shell profile 里导出着一套旧的
    bigmodel 凭据（ANTHROPIC_BASE_URL / MODEL / AUTH_TOKEN），如果用 setdefault
    就会静默拿旧值去请求，拿到的是另一个网关的定价表。
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


PRICING_FILE = ROOT_DIR / "model_pricing.json"


def load_pricing(path: Path = PRICING_FILE) -> tuple[dict[str, dict], dict]:
    """从本地 JSON 读单价。默认路径不联网。"""
    if not path.exists():
        raise FileNotFoundError(
            f"单价表不存在: {path}\n"
            f"先执行一次：uv run python scripts/agent_cost.py --refresh-pricing"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = {
        "quota_per_unit": float(data.get("quota_per_unit") or 500000),
        "usd_exchange_rate": float(data.get("usd_exchange_rate") or 7.3),
        "currency": str(data.get("currency") or "CNY"),
        "gateway": str(data.get("gateway") or ""),
        "updated_at": str(data.get("updated_at") or ""),
    }
    models = dict(data.get("models") or {})
    # 别名展开：SDK 的 model_usage 用请求名，但日志里也可能出现网关内部名
    aliases = data.get("aliases") or {}
    for alias, real in aliases.items():
        if real in models and alias not in models:
            models[alias] = models[real]
    return models, meta


def refresh_pricing(path: Path = PRICING_FILE) -> int:
    """唯一联网的命令：从网关重拉单价并覆写本地 JSON，保留原有的注释与别名。"""
    import requests

    _load_env()
    # 走 config 读取，避免这里再维护一套 ANTHROPIC_BASE_URL 的默认值
    # （原先这里默认空串、runner.py 默认 api.anthropic.com，同一个变量两个默认值）
    from rss2cubox.config import cfg as _cfg

    base_url = _cfg.str("ANTHROPIC_BASE_URL")
    token = _cfg.str("ANTHROPIC_AUTH_TOKEN") or _cfg.str("ANTHROPIC_API_KEY")
    if not token:
        print("需要 .env 里的 ANTHROPIC_AUTH_TOKEN", file=sys.stderr)
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

    # 尝试从 /api/status 拿换算参数，拿不到就沿用旧值
    meta = {
        "quota_per_unit": existing.get("quota_per_unit", 500000),
        "currency": existing.get("currency", "CNY"),
        "usd_exchange_rate": existing.get("usd_exchange_rate", 7.3),
    }
    try:
        status = requests.get(f"{base_url.rstrip('/')}/api/status", timeout=20).json().get("data", {})
        for src, dst in (("quota_per_unit", "quota_per_unit"), ("usd_exchange_rate", "usd_exchange_rate"),
                         ("quota_display_type", "currency")):
            if status.get(src) is not None:
                meta[dst] = status[src]
    except Exception:  # noqa: BLE001
        pass

    out = {
        "_readme": existing.get("_readme", [
            "模型单价表 —— 本地维护，agent_cost.py 默认只读这个文件，不联网。",
            "更新：uv run python scripts/agent_cost.py --refresh-pricing",
        ]),
        "gateway": base_url,
        "quota_per_unit": meta["quota_per_unit"],
        "currency": meta["currency"],
        "usd_exchange_rate": meta["usd_exchange_rate"],
        "updated_at": __import__("datetime").date.today().isoformat(),
        "updated_from": "网关 /api/pricing 实拉",
        "aliases": existing.get("aliases", {}),
        "models": models,
    }
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✓ 已刷新 {path.name}：{len(models)} 个模型（来自 {base_url}）")
    print(f"  换算：{meta['quota_per_unit']} quota = 1 {meta['currency']}，"
          f"1 USD = {meta['usd_exchange_rate']} {meta['currency']}")
    return 0


def compute_quota(usage: dict, price_row: dict) -> float:
    """按 new-api 的计费公式把一个 usage 字典换算成 quota。

    只算 input / output 两项，这是 new-api 对 quota_type=0 模型的实际公式。
    缓存 token 归入 input_tokens 一并统计（网关也是这么计的）。
    """
    ratio = float(price_row.get("model_ratio") or 0.0)
    completion_ratio = float(price_row.get("completion_ratio") or 1.0)

    input_tokens = float(usage.get("inputTokens", usage.get("input_tokens", 0)) or 0)
    output_tokens = float(usage.get("outputTokens", usage.get("output_tokens", 0)) or 0)

    return input_tokens * ratio + output_tokens * ratio * completion_ratio


def analyze(paths: list[str], *, prices: dict[str, dict], meta: dict) -> dict:
    per_model: dict[str, dict[str, float]] = defaultdict(
        lambda: {"calls": 0, "input": 0.0, "output": 0.0, "cache_read": 0.0,
                 "cache_create": 0.0, "quota": 0.0, "cli_cost_usd": 0.0}
    )
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
                    # 旧日志没有 model_usage，退化用 usage（无模型名）
                    usage = record.get("usage") or {}
                    if usage:
                        model_usage = {"<unknown>": usage}

                for model, usage in model_usage.items():
                    if not isinstance(usage, dict):
                        continue
                    bucket = per_model[model]
                    bucket["calls"] += 1
                    bucket["input"] += float(usage.get("inputTokens", usage.get("input_tokens", 0)) or 0)
                    bucket["output"] += float(usage.get("outputTokens", usage.get("output_tokens", 0)) or 0)
                    bucket["cache_read"] += float(
                        usage.get("cacheReadInputTokens", usage.get("cache_read_input_tokens", 0)) or 0)
                    bucket["cache_create"] += float(
                        usage.get("cacheCreationInputTokens", usage.get("cache_creation_input_tokens", 0)) or 0)
                    bucket["cli_cost_usd"] += float(cli_cost or 0.0)

                    price_row = prices.get(model)
                    if price_row is None:
                        missing_price.add(model)
                        continue
                    bucket["quota"] += compute_quota(usage, price_row)

    quota_per_unit = float(meta.get("quota_per_unit") or 500000)
    fx = float(meta.get("usd_exchange_rate") or 7.3)
    currency = meta.get("currency", "CNY")

    for bucket in per_model.values():
        bucket["amount"] = bucket["quota"] / quota_per_unit           # 以 currency 计
        bucket["amount_usd"] = bucket["amount"] / fx if fx else 0.0

    return {
        "events": events,
        "currency": currency,
        "quota_per_unit": quota_per_unit,
        "usd_exchange_rate": fx,
        "models": dict(per_model),
        "missing_price": sorted(missing_price),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="按本地单价表核算 Agent 真实成本")
    parser.add_argument("logs", nargs="*", help="JSONL 日志路径（默认取最新一次运行）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--show-pricing", action="store_true", help="只打印本地单价表")
    parser.add_argument("--refresh-pricing", action="store_true",
                        help="联网从网关重拉单价并覆写 model_pricing.json（唯一会联网的命令）")
    parser.add_argument("--pricing-file", default=str(PRICING_FILE), help="单价表路径")
    args = parser.parse_args()

    if args.refresh_pricing:
        return refresh_pricing(Path(args.pricing_file))

    try:
        prices, meta = load_pricing(Path(args.pricing_file))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.show_pricing:
        cur = meta["currency"]
        qpu = meta["quota_per_unit"]
        fx = meta["usd_exchange_rate"]
        print(f"单价表 {args.pricing_file}  (更新于 {meta['updated_at']}，来源 {meta['gateway']})")
        print(f"换算：{qpu:.0f} quota = 1 {cur}，1 USD = {fx} {cur}\n")
        hdr = (f"{'模型':28s} {'ratio':>8s} {'compl':>7s} "
               f"{f'输入{cur}/M':>11s} {f'输出{cur}/M':>11s} {'输入$/M':>10s} {'输出$/M':>10s}")
        print(hdr)
        print("-" * 92)
        for name, row in sorted(prices.items()):
            if row.get("quota_type") != 0:
                continue
            r = float(row.get("model_ratio") or 0)
            c = float(row.get("completion_ratio") or 1)
            in_amt = r * 1_000_000 / qpu
            out_amt = r * c * 1_000_000 / qpu
            print(f"{name:28s} {r:>8} {c:>7} {in_amt:>11.4f} {out_amt:>11.4f} "
                  f"{in_amt / fx:>10.5f} {out_amt / fx:>10.5f}")
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

    report = analyze(paths, prices=prices, meta=meta)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0

    cur = report["currency"]
    fx = report["usd_exchange_rate"]
    print(f"\n日志: {', '.join(paths)}")
    print(f"agent_sdk_result 事件数: {report['events']}")
    if report["missing_price"]:
        print(f"⚠ 网关定价表里没有这些模型，已跳过计费: {report['missing_price']}")

    total_amount = total_usd = total_cli = 0.0
    total_in = total_out = 0.0
    print()
    hdr = (f"{'模型':26s} {'调用':>5s} {'输入tok':>11s} {'输出tok':>9s} "
           f"{f'真实({cur})':>11s} {'真实($)':>10s} {'CLI报($)':>10s} {'高估倍数':>9s}")
    print(hdr)
    print("-" * len(hdr))
    for model, b in sorted(report["models"].items(), key=lambda x: -x[1]["amount"]):
        overstate = (b["cli_cost_usd"] / b["amount_usd"]) if b["amount_usd"] > 0 else 0.0
        print(f"{model:26s} {int(b['calls']):>5d} {int(b['input']):>11,d} {int(b['output']):>9,d} "
              f"{b['amount']:>11.4f} {b['amount_usd']:>10.4f} {b['cli_cost_usd']:>10.4f} "
              f"{overstate:>8.0f}x")
        total_amount += b["amount"]
        total_usd += b["amount_usd"]
        total_cli += b["cli_cost_usd"]
        total_in += b["input"]
        total_out += b["output"]

    print("-" * len(hdr))
    overstate = (total_cli / total_usd) if total_usd > 0 else 0.0
    print(f"{'合计':26s} {sum(int(b['calls']) for b in report['models'].values()):>5d} "
          f"{int(total_in):>11,d} {int(total_out):>9,d} "
          f"{total_amount:>11.4f} {total_usd:>10.4f} {total_cli:>10.4f} {overstate:>8.0f}x")

    if total_in:
        print(f"\n平均每次调用: 输入 {total_in / max(1, sum(b['calls'] for b in report['models'].values())):,.0f} tok"
              f"，输出 {total_out / max(1, sum(b['calls'] for b in report['models'].values())):,.0f} tok")
        print(f"真实单价约 {total_amount / (total_in / 1e6):.4f} {cur}/M 输入tok（含输出与缓存的综合折算）")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
