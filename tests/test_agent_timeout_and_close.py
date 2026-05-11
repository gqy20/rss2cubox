"""Tests for agent timeout protection & transport close safety (TDD: Red phase).

Issue 1: prediction_review_agent (and other agents) don't pass timeout_seconds
         to run_json_agent, causing indefinite hangs when SDK subprocess stalls.

Issue 2: InstrumentedSubprocessCLITransport.close() raises unhandled
         RuntimeError when async generator is still running, corrupting event loop.
"""
import sys
import time
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────
# Issue 1: Agent-level timeout defaults
# ──────────────────────────────────────────────────────────────────────

class TestPredictionReviewAgentTimeout:
    """prediction_review_agent 必须传递超时参数给 run_json_agent。"""

    def test_passes_timeout_to_run_json_agent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """run_prediction_review_agent 应将 timeout_seconds 传给 run_json_agent。"""
        from rss2cubox.prediction_review_agent import run_prediction_review_agent

        captured_kwargs: dict[str, Any] = {}

        async def fake_run(**kwargs):
            captured_kwargs.update(kwargs)
            return {
                "prediction_id": 99,
                "score": 3,
                "hit_level": "partial",
                "supporting_articles": [],
                "contradicting_articles": [],
                "actual_observation": "test",
                "why_score": "test",
                "improvement_advice": "test",
                "review_metrics": {},
            }

        monkeypatch.setattr("rss2cubox.prediction_review_agent.run_json_agent", fake_run)

        run_prediction_review_agent(
            {"id": 99, "signal_cluster_key": "test"}, [],
            log_event=lambda *a, **k: None,
        )

        assert "timeout_seconds" in captured_kwargs, \
            "run_prediction_review_agent 必须传递 timeout_seconds 参数"
        assert captured_kwargs["timeout_seconds"] is not None, \
            f"timeout_seconds 不应为 None，实际值: {captured_kwargs.get('timeout_seconds')}"
        assert captured_kwargs["timeout_seconds"] > 0, \
            f"timeout_seconds 应为正数，实际值: {captured_kwargs['timeout_seconds']}"

    def test_timeout_is_configurable_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """超时应可通过环境变量 PREDICTION_REVIEW_AGENT_TIMEOUT_SECONDS 配置。"""
        from rss2cubox.prediction_review_agent import run_prediction_review_agent

        captured_timeout = [None]

        async def fake_run(**kwargs):
            captured_timeout[0] = kwargs.get("timeout_seconds")
            return {
                "prediction_id": 1, "score": 1, "hit_level": "miss",
                "supporting_articles": [], "contradicting_articles": [],
                "actual_observation": "", "why_score": "", "improvement_advice": "",
                "review_metrics": {},
            }

        monkeypatch.setattr("rss2cubox.prediction_review_agent.run_json_agent", fake_run)
        monkeypatch.setenv("PREDICTION_REVIEW_AGENT_TIMEOUT_SECONDS", "180")

        run_prediction_review_agent({"id": 1}, [], log_event=lambda *a, **k: None)

        assert captured_timeout[0] == 180, \
            f"环境变量应覆盖默认超时，实际值: {captured_timeout[0]}"

    def test_has_sensible_default_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未设置环境变量时应有合理的默认超时（建议 ≥120s）。"""
        from rss2cubox.prediction_review_agent import run_prediction_review_agent

        captured_timeout = [None]

        async def fake_run(**kwargs):
            captured_timeout[0] = kwargs.get("timeout_seconds")
            return {
                "prediction_id": 1, "score": 1, "hit_level": "miss",
                "supporting_articles": [], "contradicting_articles": [],
                "actual_observation": "", "why_score": "", "improvement_advice": "",
                "review_metrics": {},
            }

        monkeypatch.setattr("rss2cubox.prediction_review_agent.run_json_agent", fake_run)
        # 确保没有设置自定义超时
        monkeypatch.delenv("PREDICTION_REVIEW_AGENT_TIMEOUT_SECONDS", raising=False)

        run_prediction_review_agent({"id": 1}, [], log_event=lambda *a, **k: None)

        assert captured_timeout[0] is not None, "必须有默认超时"
        assert captured_timeout[0] >= 120, \
            f"默认超时至少应为 120s，实际值: {captured_timeout[0]}"


class TestOtherAgentsHaveTimeoutDefaults:
    """其他 agent 也应有超时保护。"""

    @pytest.mark.parametrize("agent_module,agent_func,prediction_review_only", [
        ("rss2cubox.enrich_agent", None, False),
        ("rss2cubox.global_agent", None, False),
        ("rss2cubox.signal_cluster_agent", None, False),
        ("rss2cubox.prediction_agent", None, False),
        ("rss2cubox.daily_report_agent", None, False),
    ])
    def test_agents_use_timeout_helper(
        self, agent_module: str, agent_func: str,
        prediction_review_only: bool, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """所有 agent 调用 run_json_agent 时都应有超时保护。"""
        import importlib
        mod = importlib.import_module(agent_module)
        import inspect

        source = inspect.getsource(mod)
        # 接受两种超时模式：_agent_timeout() 或已有的 TIMEOUT 常量/变量
        has_timeout_helper = "_agent_timeout" in source
        has_timeout_const = "TIMEOUT" in source and "timeout_seconds" in source
        assert has_timeout_helper or has_timeout_const, \
            f"{agent_module} 应有超时保护机制（_agent_timeout 或 TIMEOUT 常量）"


# ──────────────────────────────────────────────────────────────────────
# Issue 2: Transport close() 安全性
# ──────────────────────────────────────────────────────────────────────

class TestTransportCloseSafety:
    """InstrumentedSubprocessCLITransport.close() 应安全处理竞态条件。"""

    def test_close_catches_runtime_error(self) -> None:
        """close() 的 except 子句应捕获 RuntimeError（而不仅是 Exception）。"""
        import inspect
        from rss2cubox.agent_sdk_runner import run_json_agent

        source = inspect.getsource(run_json_agent)
        # 找到 InstrumentedSubprocessCLITransport.close 方法的源码
        assert "except (RuntimeError, Exception)" in source or \
               "except RuntimeError" in source or \
               "RuntimeError" in source, \
            "close() 应显式捕获 RuntimeError（async generator 竞态的根因）"

    def test_close_uses_try_finally_for_close_done(self) -> None:
        """close() 必须使用 try/finally 确保 close_done 始终被 emit。"""
        import inspect
        from rss2cubox.agent_sdk_runner import run_json_agent

        source = inspect.getsource(run_json_agent)
        assert "finally" in source, \
            "close() 应使用 try/finally 确保 close_done 始终被 emit"

    def test_close_does_not_propagate_exception(self) -> None:
        """close() 不应将异常传播给调用方。"""
        import inspect
        import re
        from rss2cubox.agent_sdk_runner import run_json_agent

        source = inspect.getsource(run_json_agent)
        # close 方法体中，except 块不应 re-raise
        close_match = re.search(
            r"async def close\(self\).*?(?=\n    async |\n    def |\nclass )",
            source, re.DOTALL
        )
        if close_match:
            close_body = close_match.group(0)
            # except 块之后不应有 bare raise
            lines = close_body.split("\n")
            in_except = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("except"):
                    in_except = True
                elif in_except and stripped and not stripped.startswith("#") and \
                     (stripped.startswith("def ") or stripped.startswith("async ") or
                      stripped.startswith("class ") or stripped == "finally:"):
                    in_except = False
                if in_except and stripped == "raise":
                    assert False, "close() 的 except 块不应 re-raise 异常"


class TestAgentTimeoutHelper:
    """_agent_timeout() 辅助函数的单元测试。"""

    def test_returns_default_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """环境变量未设置时返回默认值。"""
        monkeypatch.delenv("TEST_AGENT_TIMEOUT", raising=False)
        from rss2cubox.agent_sdk_runner import _agent_timeout
        result = _agent_timeout("TEST_AGENT_TIMEOUT", default=300)
        assert result == 300

    def test_parses_env_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """从环境变量解析整数值。"""
        monkeypatch.setenv("TEST_AGENT_TIMEOUT", "180")
        from rss2cubox.agent_sdk_runner import _agent_timeout
        result = _agent_timeout("TEST_AGENT_TIMEOUT", default=300)
        assert result == 180

    def test_clamps_to_minimum(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """值低于下限时 clamp 到 minimum。"""
        monkeypatch.setenv("TEST_AGENT_TIMEOUT", "5")
        from rss2cubox.agent_sdk_runner import _agent_timeout
        result = _agent_timeout("TEST_AGENT_TIMEOUT", default=300, minimum=30)
        assert result == 30

    def test_returns_none_for_zero_or_negative_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """环境变量为 0 或负数时返回 None（禁用超时）。"""
        from rss2cubox.agent_sdk_runner import _agent_timeout

        for val in ["0", "-1"]:
            monkeypatch.setenv("TEST_AGENT_TIMEOUT", val)
            result = _agent_timeout("TEST_AGENT_TIMEOUT", default=300)
            assert result is None, f"值 '{val}' 应返回 None（禁用超时）"

    def test_strips_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """去除前后空白。"""
        monkeypatch.setenv("TEST_AGENT_TIMEOUT", "  250  ")
        from rss2cubox.agent_sdk_runner import _agent_timeout
        result = _agent_timeout("TEST_AGENT_TIMEOUT", default=300)
        assert result == 250
