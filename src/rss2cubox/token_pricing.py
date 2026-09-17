"""按真实单价核算 token 成本。

移植自 manim-agent 的 token_pricing.py，并扩展支持 new-api 网关的 quota 计价模式。

为什么不能直接用 claude_agent_sdk 报的 total_cost_usd：那是 CLI 按它自己的
Claude 定价表算的。走第三方网关时与真实账单无关 —— 实测同一批调用
CLI 报 $324.17，按网关单价实际 ¥14.29，高估 166 倍。

支持两种定价格式（同一个 models 表里可以混用）：

1. 直接计价（manim-agent 的格式），单位见顶层 currency，每百万 tokens：
       {"input": 2.1, "output": 8.4, "cache_read": 0.42, "cache_write": 2.625}

2. new-api 网关的 quota 倍率：
       {"model_ratio": 0.07, "completion_ratio": 2}
   配合顶层 quota_per_unit / currency / usd_exchange_rate 换算。
   cache 倍率由顶层 quota_mode_defaults 给出（见该处注释，默认按 input 同价，
   即成本上界——网关是否对 cache 打折无法从外部确认）。

两种格式都支持 tiers 分档（长上下文溢价）：
       {"tiers": [{"context_tokens_min": 0, "context_tokens_max": 32000, "input": 6.0, ...}]}
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PRICING_PATH = Path(__file__).resolve().parent.parent.parent / "model_pricing.json"

# usage 字典在不同 SDK / 网关下字段名不统一，全部兼容
# 注意同时覆盖 snake_case（Anthropic 原生 usage 字段）与 camelCase（SDK
# model_usage 的字段）。漏掉 camelCase 会导致 model_usage 解析出全零 —— 实测
# 一次 1499 条事件全部 zero 就是因为只有 snake_case。
_INPUT_KEYS = ("input_tokens", "input_token_count", "prompt_tokens", "prompt_token_count", "inputTokens")
_OUTPUT_KEYS = ("output_tokens", "output_token_count", "completion_tokens", "completion_token_count", "outputTokens")
_CACHE_READ_KEYS = ("cache_read_tokens", "cache_read_input_tokens", "cached_tokens", "cache_hit_tokens", "cacheReadInputTokens")
_CACHE_WRITE_KEYS = ("cache_write_tokens", "cache_creation_tokens", "cache_creation_input_tokens", "cacheCreationInputTokens", "cacheCreationInputTokens")
_TOTAL_KEYS = ("total_tokens", "total_token_count", "totalTokens")


@lru_cache(maxsize=1)
def load_model_pricing(path: str | None = None) -> dict[str, Any]:
    target = Path(path) if path else PRICING_PATH
    if not target.exists():
        return {}
    return json.loads(target.read_text(encoding="utf-8"))


def resolve_pricing_model(model_name: str | None, pricing: dict[str, Any] | None = None) -> str | None:
    """把模型名解析成定价表里的 key，支持 aliases 与连字符/下划线差异。"""
    if not model_name:
        return None
    data = pricing if pricing is not None else load_model_pricing()
    models = data.get("models", {})
    if model_name in models:
        return model_name

    normalized = model_name.strip().lower()
    aliases = data.get("aliases", {}) or {}
    if normalized in aliases:
        return aliases[normalized]
    compact = normalized.replace("_", "-")
    if compact in aliases:
        return aliases[compact]
    # 最后试一次大小写不敏感的模型名匹配
    for key in models:
        if key.strip().lower() == normalized:
            return key
    return None


def infer_pricing_model_name(
    model_name: str | None,
    model_usage: dict[str, Any] | None = None,
    pricing: dict[str, Any] | None = None,
) -> str | None:
    """选出最适合查价的模型名。

    SDK 的 model_usage 用「请求时的模型名」，而网关回包的 model 字段可能是内部名
    （请求 deepseek-v4-flash-aistar、回包 ds-v4-flash）。当 model_name 查不到、
    而 model_usage 只有一个条目时，用那个条目名再试一次。
    """
    data = pricing if pricing is not None else load_model_pricing()
    if resolve_pricing_model(model_name, data):
        return model_name
    if isinstance(model_usage, dict) and len(model_usage) == 1:
        candidate = next(iter(model_usage.keys()))
        resolved = resolve_pricing_model(candidate, data)
        if resolved:
            return resolved
    if isinstance(model_usage, dict):
        for candidate in model_usage:
            resolved = resolve_pricing_model(candidate, data)
            if resolved:
                return resolved
    return model_name


def _first_int(usage: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return None


def normalize_token_usage(usage: dict[str, Any] | None) -> dict[str, int | None]:
    """把各种命名的 usage 归一化。total 缺失时由四项求和。"""
    usage = usage or {}
    input_tokens = _first_int(usage, _INPUT_KEYS)
    output_tokens = _first_int(usage, _OUTPUT_KEYS)
    cache_read = _first_int(usage, _CACHE_READ_KEYS)
    cache_write = _first_int(usage, _CACHE_WRITE_KEYS)
    total = _first_int(usage, _TOTAL_KEYS)
    if total is None:
        summed = sum(v or 0 for v in (input_tokens, output_tokens, cache_read, cache_write))
        total = summed or None
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "total_tokens": total,
    }


def _quota_defaults(data: dict[str, Any]) -> dict[str, float]:
    defaults = data.get("quota_mode_defaults") or {}
    return {
        # 默认把 cache token 按 input 同价计，这是**成本上界**。
        # 网关是否对 cache_read 打折无法从外部确认，所以宁可高估也不要漏算。
        "cache_read_ratio": float(defaults.get("cache_read_ratio", 1.0)),
        "cache_write_ratio": float(defaults.get("cache_write_ratio", 1.0)),
    }


def _entry_to_rates(entry: dict[str, Any], data: dict[str, Any]) -> dict[str, float | None] | None:
    """把两种定价格式统一成 {input, output, cache_read, cache_write}（currency / 百万 tokens）。"""
    if not isinstance(entry, dict):
        return None

    if "input" in entry or "output" in entry:
        return {
            "input": entry.get("input"),
            "output": entry.get("output"),
            "cache_read": entry.get("cache_read"),
            "cache_write": entry.get("cache_write"),
        }

    ratio = entry.get("model_ratio")
    if ratio is None:
        return None
    quota_per_unit = float(data.get("quota_per_unit") or 500000)
    if quota_per_unit <= 0:
        return None
    completion_ratio = float(entry.get("completion_ratio") or 1.0)
    base = float(ratio) * 1_000_000 / quota_per_unit
    defaults = _quota_defaults(data)
    cache_read_ratio = entry.get("cache_read_ratio")
    cache_write_ratio = entry.get("cache_write_ratio")
    return {
        "input": base,
        "output": base * completion_ratio,
        "cache_read": base * float(cache_read_ratio if cache_read_ratio is not None else defaults["cache_read_ratio"]),
        "cache_write": base * float(cache_write_ratio if cache_write_ratio is not None else defaults["cache_write_ratio"]),
    }


def _pick_price_entry(
    model_name: str | None,
    context_tokens: int | None,
    pricing: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """取该模型在当前上下文长度下生效的定价条目（支持 tiers 分档）。"""
    data = pricing if pricing is not None else load_model_pricing()
    model_key = resolve_pricing_model(model_name, data)
    if not model_key:
        return None
    entry = (data.get("models") or {}).get(model_key)
    if not isinstance(entry, dict):
        return None

    tiers = entry.get("tiers")
    if not isinstance(tiers, list):
        return entry

    context = context_tokens or 0
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        minimum = tier.get("context_tokens_min") or 0
        maximum = tier.get("context_tokens_max")
        if context >= minimum and (maximum is None or context < maximum):
            return tier
    return tiers[-1] if tiers and isinstance(tiers[-1], dict) else None


def estimate_token_cost(
    model_name: str | None,
    usage: dict[str, Any] | None,
    *,
    pricing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """估算一次调用的成本，返回归一化 token 数 + 金额 + 明细 + 说明。"""
    data = pricing if pricing is not None else load_model_pricing()
    normalized = normalize_token_usage(usage)
    resolved = resolve_pricing_model(model_name, data)
    entry = _pick_price_entry(resolved, normalized["total_tokens"], data)
    currency = str(data.get("currency") or "CNY")
    fx = float(data.get("usd_exchange_rate") or 0) or None

    base = {
        **normalized,
        "model_name": model_name,
        "pricing_model": resolved,
        "currency": currency,
    }
    if not resolved or entry is None:
        return {**base, "estimated_cost": None, "estimated_cost_usd": None,
                "breakdown": {}, "note": "pricing_not_found"}

    rates = _entry_to_rates(entry, data)
    if rates is None:
        return {**base, "estimated_cost": None, "estimated_cost_usd": None,
                "breakdown": {}, "note": "unrecognized_pricing_format"}

    input_tokens = normalized["input_tokens"]
    output_tokens = normalized["output_tokens"]
    cache_read = normalized["cache_read_tokens"]
    cache_write = normalized["cache_write_tokens"]
    total = normalized["total_tokens"]

    # 只有 total、没有明细时，退化成全部按 input 计（并标注出来）
    has_breakdown = any(v is not None for v in (input_tokens, output_tokens, cache_read, cache_write))
    note = "usage_breakdown" if has_breakdown else "total_tokens_as_input"
    if not has_breakdown and total is not None:
        input_tokens = total

    def part(tokens: int | None, key: str) -> float:
        rate = rates.get(key)
        if tokens is None or not isinstance(rate, (int, float)):
            return 0.0
        return tokens * float(rate) / 1_000_000

    breakdown = {
        "input": part(input_tokens, "input"),
        "output": part(output_tokens, "output"),
        "cache_read": part(cache_read, "cache_read"),
        "cache_write": part(cache_write, "cache_write"),
    }
    amount = sum(breakdown.values())
    return {
        **base,
        "input_tokens": input_tokens,
        "estimated_cost": amount,
        "estimated_cost_usd": (amount / fx) if fx else None,
        "breakdown": breakdown,
        "rates_per_million": rates,
        "note": note,
    }


def estimate_result_cost(
    model_name: str | None,
    usage: dict[str, Any] | None,
    model_usage: dict[str, Any] | None = None,
    *,
    pricing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """估算一条 SDK ResultMessage 的成本。

    优先用 model_usage（按模型分开报的用量，最准确）；它缺失时退回 usage。
    """
    data = pricing if pricing is not None else load_model_pricing()
    inferred = infer_pricing_model_name(model_name, model_usage, data)

    if isinstance(model_usage, dict) and model_usage:
        merged: dict[str, float] = {}
        for per_model in model_usage.values():
            if not isinstance(per_model, dict):
                continue
            norm = normalize_token_usage(per_model)
            for key, value in norm.items():
                if value:
                    merged[key] = merged.get(key, 0) + value
        if merged:
            return estimate_token_cost(inferred, merged, pricing=data)

    return estimate_token_cost(inferred, usage, pricing=data)
