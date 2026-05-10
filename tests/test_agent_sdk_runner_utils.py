"""Tests for shared agent utility functions in agent_sdk_runner (TDD: Red phase)."""
from typing import Any, Callable
import pytest
from unittest.mock import MagicMock, patch


class TestMakeSdkLogger:
    """make_sdk_logger should produce a correctly parameterized sdk_logger."""

    def test_returns_none_when_log_event_is_none(self) -> None:
        """log_event=None 时返回 no-op 闭包（调用不崩溃）。"""
        from rss2cubox.agent_sdk_runner import make_sdk_logger

        logger = make_sdk_logger("test_agent", log_event=None)
        assert logger is not None
        assert callable(logger)
        logger("anything")  # 不崩溃

    def test_logs_info_by_default(self) -> None:
        """默认级别应为 INFO，stage 固定为 agent_sdk，agent 字段正确传递。"""
        from rss2cubox.agent_sdk_runner import make_sdk_logger

        log = MagicMock()
        logger = make_sdk_logger("my_agent", log_event=log)

        logger("some_event", foo="bar")
        log.assert_called_once()
        args = log.call_args[0]  # positional args tuple
        kwargs = log.call_args[1]  # keyword args dict
        assert args[0] == "INFO"
        assert args[1] == "some_event"
        assert kwargs["stage"] == "agent_sdk"
        assert kwargs["agent"] == "my_agent"
        assert kwargs["foo"] == "bar"

    def test_logs_warn_for_error_events(self) -> None:
        """以 _error 或 _no_result 结尾的事件应记为 WARN。"""
        from rss2cubox.agent_sdk_runner import make_sdk_logger

        log = MagicMock()
        logger = make_sdk_logger("x", log_event=log)

        error_patterns = ["something_failed", "agent_sdk_no_result"]
        for ev in error_patterns:
            log.reset_mock()
            logger(ev)
            log.assert_called_once()
            assert log.call_args[0][0] == "WARN"

    def test_ignores_when_log_event_absent(self) -> None:
        """log_event 缺失时静默跳过，不抛异常。"""
        from rss2cubox.agent_sdk_runner import make_sdk_logger

        logger = make_sdk_logger("x", log_event=None)
        logger("anything")  # 不崩溃


class TestMakeStderrLogger:
    """make_stderr_logger 应返回 (lines, log_fn) 元组。"""

    def test_basic_capture(self) -> None:
        """应捕获 stderr 行到 lines 列表，并返回 log 函数。"""
        from rss2cubox.agent_sdk_runner import make_stderr_logger

        lines, log = make_stderr_logger("test_prefix", limit=5)
        assert isinstance(lines, list)
        assert len(lines) == 0
        assert callable(log)

        log("hello")
        log("world")
        assert len(lines) == 2
        assert lines[0] == "hello"
        assert lines[1] == "world"

    def test_format_includes_prefix(self) -> None:
        """每行打印时应带 [prefix] 前缀。"""
        from rss2cubox.agent_sdk_runner import make_stderr_logger
        from io import StringIO
        from unittest.mock import patch

        _, log = make_stderr_logger("my_agent")
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            log("stuff")
            output = mock_out.getvalue()
        assert "[my_agent]" in output

    def test_respects_limit(self) -> None:
        """超过 limit 时旧行从头部丢弃。"""
        from rss2cubox.agent_sdk_runner import make_stderr_logger

        lines, log = make_stderr_logger("x", limit=3)
        for i in range(5):
            log(f"line-{i}")
        assert len(lines) == 3
        assert lines[-1] == "line-4"  # 最后3条: line-2, line-3, line-4

    def test_empty_lines_ignored(self) -> None:
        """空行和纯空白行不应被记录。"""
        from rss2cubox.agent_sdk_runner import make_stderr_logger

        lines, log = make_stderr_logger("x")
        log("")
        log("   ")
        assert len(lines) == 0  # 空和纯空白都被跳过


class TestBudgetHelper:
    """_budget 辅助函数应正确解析环境变量。"""

    def test_returns_none_when_env_unset(self) -> None:
        """环境变量未设置时返回 None。"""
        import os
        from rss2cubox.agent_sdk_runner import _budget

        key = f"_TEST_BUDGET_{id(os.getpid())}"
        os.environ.pop(key, None)
        result = _budget(key, "10.0")
        assert result is None

    def test_parses_valid_float(self) -> None:
        """有效浮点值应返回 float。"""
        import os
        from rss2cubox.agent_sdk_runner import _budget

        key = f"_TEST_BUDGET_{id(os.getpid())}"
        os.environ[key] = "5.5"
        result = _budget(key, "10.0")
        assert result == 5.5
        os.environ.pop(key, None)

    def test_returns_none_for_empty_string(self) -> None:
        """空字符串视为未设置。"""
        import os
        from rss2cubox.agent_sdk_runner import _budget

        key = f"_TEST_BUDGET_{id(os.getpid())}"
        os.environ[key] = ""
        result = _budget(key, "10.0")
        assert result is None
        os.environ.pop(key, None)

    def test_strips_whitespace(self) -> None:
        """值应去除前后空白。"""
        import os
        from rss2cubox.agent_sdk_runner import _budget

        key = f"_TEST_BUDGET_{id(os.getpid())}"
        os.environ[key] = "  8.5  "
        result = _budget(key, "10.0")
        assert result == 8.5
        os.environ.pop(key, None)


class TestIntegrationSdkLoggerWithAgents:
    """验证各 Agent 的 sdk_logger 可被 make_sdk_logger 替代后行为一致。"""

    @pytest.mark.parametrize("agent_name,extra_fields", [
        ("enrich", {"eid": "abc123", "url": "https://x.com"}),
        ("global", {"source_count": 42}),
        ("daily_report", {}),
        ("trend_prediction", {"cluster_count": 5}),
        ("prediction_review", {"prediction_id": "p1", "article_count": 10}),
        ("signal_cluster", {"article_count": 100}),
    ])
    def test_logger_matches_original_pattern(self, agent_name: str, extra_fields: dict) -> None:
        """每个 agent 的 sdk_logger 日志字段应与原始实现一致。"""
        from rss2cubox.agent_sdk_runner import make_sdk_logger

        log = MagicMock()
        logger = make_sdk_logger(agent_name, log_event=log)

        logger("test_event", **extra_fields)
        log.assert_called_once()
        args = log.call_args[0]
        kwargs = log.call_args[1]
        assert args[1] == "test_event"
        assert kwargs["agent"] == agent_name
        assert kwargs["stage"] == "agent_sdk"
        for k, v in extra_fields.items():
            assert kwargs[k] == v, f"字段 {k} 值不匹配"

    @pytest.mark.parametrize("agent_name", ["enrich", "global", "daily_report"])
    def test_warn_on_error_pattern(self, agent_name: str) -> None:
        """所有 agent 对 _error 和 no_result 事件都应记 WARN。"""
        from rss2cubox.agent_sdk_runner import make_sdk_logger

        log = MagicMock()
        logger = make_sdk_logger(agent_name, log_event=log)

        for ev in [f"{agent_name}_failed", "agent_sdk_no_result"]:
            log.reset_mock()
            logger(ev)
            assert log.call_args[0][0] == "WARN"


class TestRunJsonAgentTimeout:
    """run_json_agent 超时机制测试（TDD: Red→Green phase）。

    验证超时包装层的行为正确性：
    - 正常完成时返回 structured_output
    - 超时时抛出 TimeoutError 并 emit agent_sdk_error 事件
    - 无超时参数时不施加时间限制
    - 使用 asyncio.wait_for 而非 anyio.fail_after（避免 cancel scope 冲突）
    """

    @pytest.fixture()
    def _patch_sdk_imports(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock claude_agent_sdk 导入，避免真实 SDK 依赖。"""
        import types

        sdk_mock = types.ModuleType("claude_agent_sdk")
        sdk_mock.ClaudeAgentOptions = type("ClaudeAgentOptions", (), {"__init__": lambda self, **kw: None})
        sdk_mock.ResultMessage = type("ResultMessage", (), {
            "__init__": lambda self, **kw: None,
            "is_error": False,
            "subtype": "",
            "structured_output": None,
        })
        sdk_mock.query = MagicMock()
        sdk_mock.create_sdk_mcp_server = MagicMock()

        monkeypatch.setitem(sys.modules, "claude_agent_sdk", sdk_mock)

    @pytest.fixture()
    def _make_result_msg(self) -> Callable:
        """创建 ResultMessage mock 的工厂函数。"""
        from claude_agent_sdk import ResultMessage  # noqa: F811

        def _make(data: dict | None = None) -> Any:
            msg = ResultMessage()
            msg.structured_output = data
            msg.is_error = False
            msg.subtype = ""
            return msg

        return _make

    @pytest.fixture()
    def _async_gen_query(self) -> Callable:
        """创建返回 async generator 的 query mock 工厂。

        claude_agent_sdk.query() 是 async generator（用于 async for），
        不能用普通 async function mock。
        """
        def _maker(messages: list, *, delay: float = 0.0) -> Callable:
            async def _gen(**kw):
                if delay > 0:
                    import asyncio as _a
                    await _a.sleep(delay)
                for m in messages:
                    yield m
            return _gen
        return _maker

    @pytest.mark.asyncio
    async def test_returns_result_within_timeout(
        self, _patch_sdk_imports, _make_result_msg, _async_gen_query
    ) -> None:
        """query 在超时时间内正常返回 structured_output 时，应直接返回结果。"""
        from claude_agent_sdk import query  # noqa: F811

        msg = _make_result_msg({"trends": [{"text": "test"}]})
        query.side_effect = _async_gen_query([msg], delay=0.01)

        from rss2cubox.agent_sdk_runner import run_json_agent

        result = await run_json_agent(
            prompt="test",
            system_prompt="you are helpful",
            schema={"type": "object", "properties": {}},
            timeout_seconds=5.0,
        )
        assert result == {"trends": [{"text": "test"}]}

    @pytest.mark.asyncio
    async def test_raises_timeout_error_when_exceeded(
        self, _patch_sdk_imports, _async_gen_query
    ) -> None:
        """query 执行时间超过 timeout_seconds 时应抛出 TimeoutError。"""
        from claude_agent_sdk import query  # noqa: F811

        query.side_effect = _async_gen_query([], delay=10)

        from rss2cubox.agent_sdk_runner import run_json_agent

        with pytest.raises(TimeoutError):
            await run_json_agent(
                prompt="test",
                system_prompt="you are helpful",
                schema={"type": "object", "properties": {}},
                timeout_seconds=0.05,
            )

    @pytest.mark.asyncio
    async def test_emits_error_event_on_timeout(
        self, _patch_sdk_imports, _async_gen_query
    ) -> None:
        """超时时应 emit agent_sdk_error 事件。"""
        from claude_agent_sdk import query  # noqa: F811

        query.side_effect = _async_gen_query([], delay=10)

        events: list[dict] = []

        def _capture(event: str, **fields) -> None:
            events.append({"event": event, **fields})

        from rss2cubox.agent_sdk_runner import run_json_agent

        with pytest.raises(TimeoutError):
            await run_json_agent(
                prompt="test",
                system_prompt="you are helpful",
                schema={"type": "object", "properties": {}},
                timeout_seconds=0.05,
                sdk_log=_capture,
            )

        error_events = [e for e in events if e["event"] == "agent_sdk_error"]
        assert len(error_events) >= 1
        assert "error" in error_events[0]

    @pytest.mark.asyncio
    async def test_no_timeout_when_zero_or_none(
        self, _patch_sdk_imports, _make_result_msg, _async_gen_query
    ) -> None:
        """timeout_seconds 为 None 或 0 时不应施加超时限制。"""
        from claude_agent_sdk import query  # noqa: F811

        msg = _make_result_msg({"ok": True})

        from rss2cubox.agent_sdk_runner import run_json_agent

        # None
        query.side_effect = _async_gen_query([msg], delay=0.01)
        r1 = await run_json_agent(
            prompt="test",
            system_prompt="help",
            schema={"type": "object", "properties": {}},
            timeout_seconds=None,
        )
        assert r1 == {"ok": True}

        # 0
        query.side_effect = _async_gen_query([msg], delay=0.01)
        r2 = await run_json_agent(
            prompt="test",
            system_prompt="help",
            schema={"type": "object", "properties": {}},
            timeout_seconds=0,
        )
        assert r2 == {"ok": True}

    def test_does_not_use_anyio_fail_after(self) -> None:
        """实现不应依赖 anyio.fail_after（避免与 SDK cancel scope 冲突）。"""
        import inspect
        from rss2cubox.agent_sdk_runner import run_json_agent

        source = inspect.getsource(run_json_agent)
        assert "fail_after" not in source, \
            "run_json_agent 不应使用 anyio.fail_after，应改用 asyncio.wait_for 避免 cancel scope 冲突"

    def test_uses_asyncio_wait_for(self) -> None:
        """实现应使用 asyncio.wait_for 进行超时控制。"""
        import inspect
        from rss2cubox.agent_sdk_runner import run_json_agent

        source = inspect.getsource(run_json_agent)
        assert "wait_for" in source, \
            "run_json_agent 应使用 asyncio.wait_for 替代 anyio.fail_after"


class TestEnrichRetry:
    """_enrich_one 超时退避重试机制测试。

    验证：
    - TimeoutError 触发退避重试，非 TimeoutError 不重试
    - 重试成功后返回结果
    - 重试耗尽后返回 None
    - ENRICH_MAX_RETRIES=0 时无重试
    """

    @pytest.fixture(autouse=True)
    def _patch_environ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """为测试固定环境变量（BACKOFF=0 避免真实等待）。"""
        monkeypatch.setenv("ENRICH_MAX_RETRIES", "1")
        monkeypatch.setenv("ENRICH_RETRY_BACKOFF_SECONDS", "0")
        monkeypatch.setenv("ENRICH_ITEM_TIMEOUT_SECONDS", "5")
        monkeypatch.setenv("ENRICH_MAX_BUDGET_USD", "")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    @staticmethod
    def _sample_item() -> dict:
        return {
            "eid": "test-retry-eid-001",
            "url": "https://example.com/article",
            "title": "Test Article",
            "description": "A test article for retry logic",
        }

    @staticmethod
    def _sample_original() -> dict:
        return {"core_event": "", "reason": "", "hidden_signal": "", "actionable": "", "tags": []}

    @staticmethod
    def _expected_result(core: str = "test") -> dict:
        return {
            "core_event": core,
            "reason": "r",
            "hidden_signal": "h",
            "actionable": "a",
            "tags": [],
            "importance_score": 3,
            "content_source": "full_text",
            "signal_type": 1,
            "evidence_type": 2,
            "evidence_strength": 3,
            "novelty_score": 3,
            "impact_horizon": 3,
            "audience": [2],
            "market_stage": 4,
            "confidence": 4,
            "entities": [],
            "cluster_hint": "",
            "watch_keywords": [],
            "prediction": "",
            "disconfirming_evidence": "",
        }

    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self) -> None:
        """首次调用即成功时，不应触发重试，直接返回结果。"""
        expected = self._expected_result()

        with patch("rss2cubox.enrich_agent.run_json_agent", return_value=expected) as mock_run:
            from rss2cubox.enrich_agent import _enrich_one

            result, reason = await _enrich_one(self._sample_item(), self._sample_original())
            assert result is not None
            assert result["core_event"] == "test"
            assert reason == "ok"
            assert mock_run.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self) -> None:
        """首次超时、重试成功时应返回结果。"""
        expected = self._expected_result("retry-ok")
        call_count = 0

        def _side_effect(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("simulated timeout")
            return expected

        with patch("rss2cubox.enrich_agent.run_json_agent", side_effect=_side_effect) as mock_run:
            from rss2cubox.enrich_agent import _enrich_one

            result, reason = await _enrich_one(self._sample_item(), self._sample_original())
            assert result is not None
            assert result["core_event"] == "retry-ok"
            assert reason == "ok"
            assert mock_run.call_count == 2

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_returns_none(self) -> None:
        """所有尝试都超时时返回 None 并携带耗尽信息。"""
        with patch(
            "rss2cubox.enrich_agent.run_json_agent",
            side_effect=TimeoutError("simulated timeout"),
        ) as mock_run:
            from rss2cubox.enrich_agent import _enrich_one

            result, reason = await _enrich_one(self._sample_item(), self._sample_original())
            assert result is None
            assert "timeout_after" in reason
            assert "2_attempts" in reason
            assert mock_run.call_count == 2

    @pytest.mark.asyncio
    async def test_non_timeout_error_no_retry(self) -> None:
        """非 TimeoutError（如 RuntimeError）不应触发重试。"""
        with patch(
            "rss2cubox.enrich_agent.run_json_agent",
            side_effect=RuntimeError("sdk_connection_failed"),
        ) as mock_run:
            from rss2cubox.enrich_agent import _enrich_one

            result, reason = await _enrich_one(self._sample_item(), self._sample_original())
            assert result is None
            assert reason == "sdk_connection_failed"
            assert mock_run.call_count == 1

    @pytest.mark.asyncio
    async def test_zero_retries_no_retry_on_timeout(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ENRICH_MAX_RETRIES=0 时超时不重试，直接失败。"""
        import rss2cubox.enrich_agent

        # 直接 patch 模块级常量（reload 对 os.getenv 重新求值在某些场景不生效）
        monkeypatch.setattr(rss2cubox.enrich_agent, "ENRICH_MAX_RETRIES", 0)

        with patch(
            "rss2cubox.enrich_agent.run_json_agent",
            side_effect=TimeoutError("simulated timeout"),
        ) as mock_run:
            from rss2cubox.enrich_agent import _enrich_one

            result, reason = await _enrich_one(self._sample_item(), self._sample_original())
            assert result is None
            assert "timeout_after_1_attempts" in reason
            assert mock_run.call_count == 1


import sys  # noqa: E402
