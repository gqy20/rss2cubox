"""scripts/agent_cost.py 的计费数学测试。

这里的数字算错是"静默给出错误金额"，比崩溃更糟，所以公式要用实测值锁死。
agent_cost.py 是脚本不是包，用 importlib 按路径加载。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "agent_cost.py"

spec = importlib.util.spec_from_file_location("agent_cost", SCRIPT)
agent_cost = importlib.util.module_from_spec(spec)
sys.modules["agent_cost"] = agent_cost
spec.loader.exec_module(agent_cost)


# 实测锚点：2026-09-16 一次真实调用，CLI 报 costUSD=0.114978
MEASURED_USAGE = {
    "inputTokens": 38071,
    "outputTokens": 51,
    "cacheReadInputTokens": 0,
    "cacheCreationInputTokens": 0,
}
DEEPSEEK_FLASH = {"quota_type": 0, "model_ratio": 0.07, "completion_ratio": 2, "model_price": 0}


class TestComputeQuota:
    def test_measured_call_matches_manual_math(self) -> None:
        """38071×0.07 + 51×0.07×2 = 2664.97 + 7.14 = 2672.11 quota"""
        quota = agent_cost.compute_quota(MEASURED_USAGE, DEEPSEEK_FLASH)
        assert quota == pytest.approx(38071 * 0.07 + 51 * 0.07 * 2)
        assert quota == pytest.approx(2672.11, abs=0.01)

    def test_quota_to_cny(self) -> None:
        quota = agent_cost.compute_quota(MEASURED_USAGE, DEEPSEEK_FLASH)
        assert quota / 500000 == pytest.approx(0.00534, abs=1e-5)

    def test_output_costs_completion_ratio_times_input(self) -> None:
        one_in = agent_cost.compute_quota({"inputTokens": 1000, "outputTokens": 0}, DEEPSEEK_FLASH)
        one_out = agent_cost.compute_quota({"inputTokens": 0, "outputTokens": 1000}, DEEPSEEK_FLASH)
        assert one_out == pytest.approx(one_in * 2)

    def test_accepts_snake_case_usage_too(self) -> None:
        """SDK 的 usage 用 snake_case，model_usage 用 camelCase，两种都要能吃。"""
        camel = agent_cost.compute_quota(
            {"inputTokens": 1000, "outputTokens": 500}, DEEPSEEK_FLASH)
        snake = agent_cost.compute_quota(
            {"input_tokens": 1000, "output_tokens": 500}, DEEPSEEK_FLASH)
        assert camel == snake

    def test_missing_fields_treated_as_zero(self) -> None:
        assert agent_cost.compute_quota({}, DEEPSEEK_FLASH) == 0.0
        assert agent_cost.compute_quota({"inputTokens": None, "outputTokens": None}, DEEPSEEK_FLASH) == 0.0

    def test_zero_ratio_yields_zero(self) -> None:
        assert agent_cost.compute_quota(MEASURED_USAGE, {"model_ratio": 0, "completion_ratio": 2}) == 0.0

    def test_missing_completion_ratio_defaults_to_one(self) -> None:
        row = {"model_ratio": 0.1}
        quota = agent_cost.compute_quota({"inputTokens": 0, "outputTokens": 1000}, row)
        assert quota == pytest.approx(100.0)


class TestLoadPricing:
    def test_loads_repo_pricing_file_offline(self) -> None:
        """默认路径必须完全离线 —— 这是这个脚本存在的理由之一。"""
        models, meta = agent_cost.load_pricing(ROOT / "model_pricing.json")
        assert "deepseek-v4-flash-aistar" in models
        assert meta["quota_per_unit"] == 500000
        assert meta["currency"] == "CNY"
        assert meta["usd_exchange_rate"] == 7.3

    def test_current_model_pricing_matches_gateway(self) -> None:
        """锁死当前生产模型的单价，网关调价时这个测试会提醒更新。"""
        models, _ = agent_cost.load_pricing(ROOT / "model_pricing.json")
        row = models["deepseek-v4-flash-aistar"]
        assert row["model_ratio"] == 0.07
        assert row["completion_ratio"] == 2
        assert row["quota_type"] == 0

    def test_alias_resolves_to_real_model(self) -> None:
        """网关回包里 model 字段可能是内部名（ds-v4-flash），要能映射回定价。"""
        models, _ = agent_cost.load_pricing(ROOT / "model_pricing.json")
        assert "ds-v4-flash" in models
        assert models["ds-v4-flash"]["model_ratio"] == models["deepseek-v4-flash-aistar"]["model_ratio"]

    def test_missing_file_raises_with_hint(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="refresh-pricing"):
            agent_cost.load_pricing(tmp_path / "nope.json")

    def test_custom_file(self, tmp_path: Path) -> None:
        p = tmp_path / "p.json"
        p.write_text(json.dumps({
            "quota_per_unit": 100, "currency": "USD", "usd_exchange_rate": 1,
            "models": {"m": {"model_ratio": 1, "completion_ratio": 1, "quota_type": 0}},
            "aliases": {"alias": "m"},
        }), encoding="utf-8")
        models, meta = agent_cost.load_pricing(p)
        assert meta["currency"] == "USD" and meta["quota_per_unit"] == 100
        assert set(models) == {"m", "alias"}


class TestAnalyze:
    def _log(self, tmp_path: Path, records: list[dict]) -> str:
        p = tmp_path / "run.jsonl"
        p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
        return str(p)

    def test_sums_tokens_and_computes_real_cost(self, tmp_path: Path) -> None:
        path = self._log(tmp_path, [
            {"event": "agent_sdk_result", "total_cost_usd": 0.114978,
             "model_usage": {"deepseek-v4-flash-aistar": MEASURED_USAGE}},
            {"event": "agent_sdk_result", "total_cost_usd": 0.114978,
             "model_usage": {"deepseek-v4-flash-aistar": MEASURED_USAGE}},
        ])
        models, meta = agent_cost.load_pricing(ROOT / "model_pricing.json")
        report = agent_cost.analyze([path], prices=models, meta=meta)

        assert report["events"] == 2
        bucket = report["models"]["deepseek-v4-flash-aistar"]
        assert bucket["calls"] == 2
        assert bucket["input"] == 38071 * 2
        assert bucket["amount"] == pytest.approx(0.00534 * 2, abs=1e-5)
        assert bucket["cli_cost_usd"] == pytest.approx(0.114978 * 2)
        # CLI 的 Claude 价对真实单价的高估倍数必须被算出来
        assert bucket["cli_cost_usd"] / bucket["amount_usd"] > 100

    def test_ignores_non_result_events(self, tmp_path: Path) -> None:
        path = self._log(tmp_path, [
            {"event": "run_start"},
            {"event": "enrich_item_start", "eid": "x"},
            {"event": "agent_sdk_result", "model_usage": {"deepseek-v4-flash-aistar": MEASURED_USAGE}},
        ])
        models, meta = agent_cost.load_pricing(ROOT / "model_pricing.json")
        assert agent_cost.analyze([path], prices=models, meta=meta)["events"] == 1

    def test_falls_back_to_usage_when_model_usage_absent(self, tmp_path: Path) -> None:
        """旧日志没有 model_usage，应退化用 usage 并标为 <unknown>。"""
        path = self._log(tmp_path, [
            {"event": "agent_sdk_result", "total_cost_usd": 0.1,
             "usage": {"input_tokens": 1000, "output_tokens": 100}},
        ])
        models, meta = agent_cost.load_pricing(ROOT / "model_pricing.json")
        report = agent_cost.analyze([path], prices=models, meta=meta)
        assert "<unknown>" in report["models"]
        assert report["models"]["<unknown>"]["input"] == 1000

    def test_unknown_model_reported_not_silently_zero(self, tmp_path: Path) -> None:
        """单价表里没有的模型必须被报出来，否则金额会静默偏低。"""
        path = self._log(tmp_path, [
            {"event": "agent_sdk_result", "model_usage": {"gpt-9-turbo": MEASURED_USAGE}},
        ])
        models, meta = agent_cost.load_pricing(ROOT / "model_pricing.json")
        report = agent_cost.analyze([path], prices=models, meta=meta)
        assert report["missing_price"] == ["gpt-9-turbo"]
        assert report["models"]["gpt-9-turbo"]["amount"] == 0.0

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.jsonl"
        p.write_text('not json\n{"broken":\n' + json.dumps(
            {"event": "agent_sdk_result", "model_usage": {"deepseek-v4-flash-aistar": MEASURED_USAGE}}
        ) + "\n", encoding="utf-8")
        models, meta = agent_cost.load_pricing(ROOT / "model_pricing.json")
        assert agent_cost.analyze([str(p)], prices=models, meta=meta)["events"] == 1

    def test_missing_file_is_safe(self, tmp_path: Path) -> None:
        models, meta = agent_cost.load_pricing(ROOT / "model_pricing.json")
        report = agent_cost.analyze([str(tmp_path / "nope.jsonl")], prices=models, meta=meta)
        assert report["events"] == 0 and report["models"] == {}
