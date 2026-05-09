"""Tests for shared agent utility functions in agent_sdk_runner (TDD: Red phase)."""
import pytest
from unittest.mock import MagicMock


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
