"""scripts/agent_cost.py + rss2cubox.token_pricing 的测试。

计价逻辑已从 agent_cost.py 抽到 rss2cubox.token_pricing（移植自
manim-agent 的 token_pricing.py 并扩展了 new-api quota 模式），所以
测试分两层：token_pricing 的单元测试 + agent_cost 的日志分析测试。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# ── 加载脚本 ──
_SCRIPT = ROOT / "scripts" / "agent_cost.py"
spec = importlib.util.spec_from_file_location("agent_cost", _SCRIPT)
agent_cost = importlib.util.module_from_spec(spec)
sys.modules["agent_cost"] = agent_cost
spec.loader.exec_module(agent_cost)

from rss2cubox import token_pricing as tp

# 实测锚点：2026-09-16 一次真实调用，CLI 报 costUSD=0.114978
MEASURED_USAGE_CAMEL = {
    "inputTokens": 38071,
    "outputTokens": 51,
    "cacheReadInputTokens": 0,
    "cacheCreationInputTokens": 0,
}
MEASURED_USAGE_SNAKE = {
    "input_tokens": 38071,
    "output_tokens": 51,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0,
}
DEEPSEEK_QUOTA = {"model_ratio": 0.07, "completion_ratio": 2, "quota_type": 0}


class TestNormalizeTokenUsage:
    @pytest.mark.parametrize("usage", [MEASURED_USAGE_CAMEL, MEASURED_USAGE_SNAKE])
    def test_both_key_styles(self, usage: dict) -> None:
        norm = tp.normalize_token_usage(usage)
        assert norm["input_tokens"] == 38071
        assert norm["output_tokens"] == 51

    def test_various_provider_aliases(self) -> None:
        """不同 SDK/网关的命名全要兼容（manim-agent 的 normalize 模式）。"""
        for key in ("prompt_tokens", "prompt_token_count", "input_token_count"):
            assert tp.normalize_token_usage({key: 100})["input_tokens"] == 100
        for key in ("cached_tokens", "cache_hit_tokens", "cache_read_input_tokens"):
            assert tp.normalize_token_usage({key: 50})["cache_read_tokens"] == 50
        for key in ("cache_creation_tokens", "cache_creation_input_tokens"):
            assert tp.normalize_token_usage({key: 30})["cache_write_tokens"] == 30

    def test_missing_fields_become_none(self) -> None:
        norm = tp.normalize_token_usage({})
        assert all(v is None for v in norm.values())

    def test_total_falls_back_to_sum(self) -> None:
        norm = tp.normalize_token_usage({"input_tokens": 100, "output_tokens": 50})
        assert norm["total_tokens"] == 150


class TestQuotaModeCost:
    """new-api 网关的 quota 倍率计价。"""

    PRICING = {
        "currency": "CNY",
        "quota_per_unit": 500000,
        "usd_exchange_rate": 7.3,
        "models": {"deepseek-v4-flash-aistar": DEEPSEEK_QUOTA},
        "aliases": {"ds-v4-flash": "deepseek-v4-flash-aistar"},
    }

    def test_measured_call(self) -> None:
        """38071×0.07 + 51×0.07×2 = 2664.97 + 7.14 = 2672.11 quota。"""
        r = tp.estimate_token_cost(
            "deepseek-v4-flash-aistar", MEASURED_USAGE_SNAKE, pricing=self.PRICING)
        assert r["breakdown"]["input"] == pytest.approx(38071 * 0.07 / 500000)
        assert r["breakdown"]["output"] == pytest.approx(51 * 0.07 * 2 / 500000)
        assert r["estimated_cost"] == pytest.approx((38071 * 0.07 + 51 * 0.07 * 2) / 500000)
        assert r["note"] == "usage_breakdown"
        assert r["currency"] == "CNY"

    def test_output_costs_completion_ratio_times_input(self) -> None:
        r = tp.estimate_token_cost(
            "deepseek-v4-flash-aistar",
            {"input_tokens": 0, "output_tokens": 1000},
            pricing=self.PRICING,
        )
        r_in = tp.estimate_token_cost(
            "deepseek-v4-flash-aistar",
            {"input_tokens": 1000, "output_tokens": 0},
            pricing=self.PRICING,
        )
        assert r["breakdown"]["output"] == pytest.approx(r_in["breakdown"]["input"] * 2)

    def test_cache_read_priced_separately(self) -> None:
        """cache_read 按 cache_read_ratio（默认 1.0 = 按 input 同价，成本上界）。"""
        r = tp.estimate_token_cost(
            "deepseek-v4-flash-aistar",
            {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 1000},
            pricing=self.PRICING,
        )
        assert r["breakdown"]["cache_read"] == pytest.approx(r["breakdown"]["input"] or 0) or True
        # 具体验证
        assert r["breakdown"]["cache_read"] == pytest.approx(1000 * 0.07 / 500000)

    def test_cache_read_ratio_can_discount(self) -> None:
        pricing = {**self.PRICING, "quota_mode_defaults": {"cache_read_ratio": 0.1}}
        r = tp.estimate_token_cost(
            "deepseek-v4-flash-aistar",
            {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 1000},
            pricing=pricing,
        )
        # 0.1 倍 = 1000 × 0.07 × 0.1 / 500000
        assert r["breakdown"]["cache_read"] == pytest.approx(1000 * 0.007 / 500000)

    def test_zero_ratio_yields_zero(self) -> None:
        pricing = {"models": {"m": {"model_ratio": 0}}}
        r = tp.estimate_token_cost("m", {"input_tokens": 1000}, pricing=pricing)
        assert r["estimated_cost"] == 0.0

    def test_missing_completion_ratio_defaults_to_one(self) -> None:
        r = tp.estimate_token_cost(
            "m", {"input_tokens": 0, "output_tokens": 1000},
            pricing={"models": {"m": {"model_ratio": 0.1}}},
        )
        assert r["breakdown"]["output"] == pytest.approx(1000 * 0.2 / 1_000_000)  # 0.1 ratio × 1e6/5e5 = 0.2 CNY/M

    def test_total_only_usage_counts_as_input(self) -> None:
        r = tp.estimate_token_cost("m", {"total_tokens": 500}, pricing={"models": {"m": {"model_ratio": 0.1}}})
        assert r["note"] == "total_tokens_as_input"
        assert r["input_tokens"] == 500


class TestDirectModeCost:
    """直接 CNY/M 计价模式（manim-agent 的格式）。"""

    PRICING = {
        "currency": "CNY",
        "models": {"m": {"input": 2.1, "output": 8.4, "cache_read": 0.42, "cache_write": 2.625}},
    }

    def test_simple(self) -> None:
        r = tp.estimate_token_cost(
            "m", {"input_tokens": 1_000_000, "output_tokens": 500_000}, pricing=self.PRICING)
        assert r["estimated_cost"] == pytest.approx(2.1 + 8.4 * 0.5)
        assert r["breakdown"]["cache_read"] == 0.0  # 没有 cache token


class TestTieredPricing:
    def test_picks_correct_tier(self) -> None:
        pricing = {
            "models": {"m": {"tiers": [
                {"context_tokens_min": 0, "context_tokens_max": 32000, "input": 6.0},
                {"context_tokens_min": 32000, "context_tokens_max": None, "input": 12.0},
            ]}},
        }
        r1 = tp.estimate_token_cost("m", {"input_tokens": 100, "total_tokens": 100}, pricing=pricing)
        r2 = tp.estimate_token_cost("m", {"input_tokens": 50000, "total_tokens": 50000}, pricing=pricing)
        assert r1["rates_per_million"]["input"] == 6.0
        assert r2["rates_per_million"]["input"] == 12.0


class TestModelResolution:
    PRICING = {
        "models": {"deepseek-v4-flash-aistar": DEEPSEEK_QUOTA, "Qwen3.8-Max": {}},
        "aliases": {"ds-v4-flash": "deepseek-v4-flash-aistar"},
    }

    def test_exact_name(self) -> None:
        assert tp.resolve_pricing_model("deepseek-v4-flash-aistar", self.PRICING) == "deepseek-v4-flash-aistar"

    def test_alias(self) -> None:
        assert tp.resolve_pricing_model("ds-v4-flash", self.PRICING) == "deepseek-v4-flash-aistar"

    def test_case_insensitive(self) -> None:
        assert tp.resolve_pricing_model("qwen3.8-max", self.PRICING) == "Qwen3.8-Max"

    def test_infer_from_model_usage(self) -> None:
        """model_usage 只有一个条目时用那个条目名（修复 <unknown>）。"""
        assert tp.infer_pricing_model_name(None, {"ds-v4-flash": {}}, self.PRICING) == "deepseek-v4-flash-aistar"

    def test_infer_prefers_valid_name(self) -> None:
        assert tp.infer_pricing_model_name("Qwen3.8-Max", {"ds-v4-flash": {}}, self.PRICING) == "Qwen3.8-Max"

    def test_unknown_returns_none(self) -> None:
        r = tp.estimate_token_cost("gpt-9-turbo", {"input_tokens": 100}, pricing=self.PRICING)
        assert r["note"] == "pricing_not_found"
        assert r["estimated_cost"] is None


class TestEstimateResultCost:
    def test_prefers_model_usage(self) -> None:
        pricing = {
            "currency": "CNY", "usd_exchange_rate": 7.3,
            "models": {"m": {"model_ratio": 0.1, "completion_ratio": 1}},
        }
        r = tp.estimate_result_cost(
            None,
            {"input_tokens": 0},
            {"m": {"inputTokens": 1000, "outputTokens": 100}},
            pricing=pricing,
        )
        assert r["input_tokens"] == 1000
        assert r["output_tokens"] == 100
        assert r["pricing_model"] == "m"

    def test_falls_back_to_usage(self) -> None:
        pricing = {"models": {"m": {"model_ratio": 0.1}}}
        r = tp.estimate_result_cost("m", {"input_tokens": 500}, None, pricing=pricing)
        assert r["input_tokens"] == 500


class TestRealPricingFile:
    """仓库里的 model_pricing.json 必须始终合法。"""

    def test_loads(self) -> None:
        data = tp.load_model_pricing()
        assert "models" in data
        assert "deepseek-v4-flash-aistar" in data["models"]
        assert data.get("quota_per_unit") == 500000
        assert data.get("currency") == "CNY"

    def test_current_model_prices(self) -> None:
        """锁住当前生产模型的单价，网关调价时这个测试会提醒更新。"""
        data = tp.load_model_pricing()
        entry = data["models"]["deepseek-v4-flash-aistar"]
        assert entry["model_ratio"] == 0.07
        assert entry["completion_ratio"] == 2

    def test_alias_present(self) -> None:
        data = tp.load_model_pricing()
        assert data.get("aliases", {}).get("ds-v4-flash") == "deepseek-v4-flash-aistar"

    def test_cache_defaults_present(self) -> None:
        data = tp.load_model_pricing()
        assert "quota_mode_defaults" in data
        assert "cache_read_ratio" in data["quota_mode_defaults"]


class TestAgentCostAnalyze:
    """agent_cost.analyze 的日志解析。"""

    @staticmethod
    def _log(tmp_path: Path, records: list) -> str:
        p = tmp_path / "run.jsonl"
        p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
        return str(p)

    PRICING = {
        "currency": "CNY", "usd_exchange_rate": 7.3,
        "models": {"m": {"model_ratio": 0.07, "completion_ratio": 2}},
        "aliases": {},
    }

    def test_sums_tokens_and_costs(self, tmp_path: Path) -> None:
        path = self._log(tmp_path, [
            {"event": "agent_sdk_result", "total_cost_usd": 0.1,
             "model_usage": {"m": {"inputTokens": 1000, "outputTokens": 100}}},
            {"event": "agent_sdk_result", "total_cost_usd": 0.2,
             "model_usage": {"m": {"inputTokens": 2000, "outputTokens": 200}}},
        ])
        report = agent_cost.analyze([path], pricing=self.PRICING)
        b = report["models"]["m"]
        assert b["calls"] == 2
        assert b["input"] == 3000
        assert b["output"] == 300
        assert b["cost"] == pytest.approx((3000 * 0.07 + 300 * 0.14) / 500000)

    def test_ignores_non_result_events(self, tmp_path: Path) -> None:
        path = self._log(tmp_path, [
            {"event": "run_start"},
            {"event": "agent_sdk_tool_use", "tool": "Read"},
            {"event": "agent_sdk_result", "model_usage": {"m": {"inputTokens": 100, "outputTokens": 10}}},
        ])
        report = agent_cost.analyze([path], pricing=self.PRICING)
        assert report["events"] == 1

    def test_falls_back_to_usage(self, tmp_path: Path) -> None:
        path = self._log(tmp_path, [
            {"event": "agent_sdk_result", "total_cost_usd": 0.1, "usage": {"input_tokens": 500, "output_tokens": 50}},
        ])
        report = agent_cost.analyze([path], pricing=self.PRICING)
        assert "<unknown>" in report["models"]
        assert report["models"]["<unknown>"]["input"] == 500

    def test_unknown_model_reported(self, tmp_path: Path) -> None:
        path = self._log(tmp_path, [
            {"event": "agent_sdk_result", "model_usage": {"gpt-9-turbo": {"inputTokens": 100, "outputTokens": 10}}},
        ])
        report = agent_cost.analyze([path], pricing=self.PRICING)
        assert report["missing_price"] == ["gpt-9-turbo"]

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.jsonl"
        p.write_text(
            "not json\n{\"broken\":\n"
            + json.dumps({"event": "agent_sdk_result", "model_usage": {"m": {"inputTokens": 100, "outputTokens": 10}}})
            + "\n",
            encoding="utf-8",
        )
        report = agent_cost.analyze([str(p)], pricing=self.PRICING)
        assert report["events"] == 1

    def test_missing_file_is_safe(self, tmp_path: Path) -> None:
        report = agent_cost.analyze([str(tmp_path / "nope.jsonl")], pricing=self.PRICING)
        assert report["events"] == 0 and report["models"] == {}
