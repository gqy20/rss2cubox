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
        monkeypatch.setenv("PREDICTION_REVIEW_AGENT_TIMEOUT_SECONDS", "42")

        run_prediction_review_agent({"id": 1}, [], log_event=lambda *a, **k: None)

        assert captured_timeout[0] == 42, \
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
        """所有 agent 调用 run_json_agent 时都应通过 _agent_timeout() 获取超时。"""
        import importlib
        mod = importlib.import_module(agent_module)

        # 验证模块中存在 _agent_timeout 辅助函数或等价机制
        assert hasattr(mod, "_agent_timeout") or hasattr(mod, "_get_agent_timeout"), \
            f"{agent_module} 应定义 _agent_timeout() 辅助函数"


# ──────────────────────────────────────────────────────────────────────
# Issue 2: Transport close() 安全性
# ──────────────────────────────────────────────────────────────────────

class TestTransportCloseSafety:
    """InstrumentedSubprocessCLITransport.close() 应安全处理竞态条件。"""

    @pytest.fixture()
    def _patch_sdk_imports(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock claude_agent_sdk 导入。"""
        import types

        sdk_mock = types.ModuleType("claude_agent_sdk")
        sdk_mock.ClaudeAgentOptions = type("ClaudeAgentOptions", (), {"__init__": lambda self, **kw: None})

        # Mock SubprocessCLITransport base class
        class FakeBaseTransport:
            async def connect(self): pass
            async def write(self, data): pass
            async def close(self): pass

        try:
            from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
        except ImportError:
            SubprocessCLITransport = FakeBaseTransport  # type: ignore[assignment]

        sdk_mock.SubprocessCLITransport = SubprocessCLITransport
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", sdk_mock)

        # Mock internal transport module
        _internal = types.ModuleType("claude_agent_sdk._internal")
        _transport = types.ModuleType("claude_agent_sdk._internal.transport")
        _subprocess = types.ModuleType("claude_agent_sdk._internal.transport.subprocess_cli")
        _subprocess.SubprocessCLITransport = SubprocessCLITransport
        sys.modules["claude_agent_sdk._internal"] = _internal
        sys.modules["claude_agent_sdk._internal.transport"] = _transport
        sys.modules["claude_agent_sdk._internal.transport.subprocess_cli"] = _subprocess

    @pytest.mark.asyncio
    async def test_close_handles_runtime_error_gracefully(
        self, _patch_sdk_imports, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """close() 中 super().close() 抛出 RuntimeError 时不应传播异常。"""
        from rss2cubox.agent_sdk_runner import InstrumentedSubprocessCLITransport

        events: list[dict] = []

        def _capture(event: str, **fields):
            events.append({"event": event, **fields})

        transport = InstrumentedSubprocessCLITransport.__new__(InstrumentedSubprocessCLITransport)
        transport._write_count = 0

        # Patch emit to capture events
        original_emit = lambda e, **kw: events.append({"event": e, **kw})

        # Make super().close() raise RuntimeError (the real bug)
        original_close = InstrumentedSubprocessCLITransport.__bases__[0].close if InstrumentedSubprocessCLITransport.__bases__ else None

        async def broken_close(self):
            raise RuntimeError("aclose(): asynchronous generator is already running")

        with patch.object(
            InstrumentedSubprocessCLITransport.__bases__[0] if InstrumentedSubprocessCLITransport.__bases__ else type("Fake", (), {"close": lambda self: None}),
            "close",
            side_effect=broken_close,
        ):
            # Should NOT raise
            result = await transport.close()

        # close_done event should still be emitted
        close_events = [e for e in events if "close" in e.get("event", "")]
        assert len(close_events) >= 1, "即使 close 出错也应 emit close_done 事件"

    @pytest.mark.asyncio
    async def test_close_always_emits_close_done(
        self, _patch_sdk_imports, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """无论成功还是异常，close() 都必须 emit close_done 事件。"""
        from rss2cubox.agent_sdk_runner import InstrumentedSubprocessCLITransport

        events: list[dict] = []

        transport = InstrumentedSubprocessCLITransport.__new__(InstrumentedSubprocessCLITransport)
        transport._write_count = 0

        async def normal_close(self):
            pass

        # Test normal path
        with patch.object(type(transport), "close", wraps=lambda self: normal_close(self)):
            await transport.close()

        # We verify the implementation uses try/finally pattern
        import inspect
        source = inspect.getsource(InstrumentedSubprocessCLITransport.close)
        assert "finally" in source, \
            "close() 应使用 try/finally 确保 close_done 始终被 emit"


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
