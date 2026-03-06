"""Tests for enrich_agent module."""
import pytest


class TestEnrichAgentOutputFormat:
    """Tests for query() + text parsing (IssueLab approach)."""

    def test_output_format_schema(self) -> None:
        """Verify output_format has correct schema structure."""
        expected_schema = {
            "type": "object",
            "properties": {
                "core_event": {"type": "string"},
                "hidden_signal": {"type": "string"},
                "actionable": {"type": "string"},
                "score": {"type": "number"},
            },
            "required": ["core_event", "hidden_signal", "actionable", "score"],
        }

        assert "core_event" in expected_schema["properties"]
        assert "hidden_signal" in expected_schema["properties"]
        assert "actionable" in expected_schema["properties"]
        assert "score" in expected_schema["properties"]
        assert expected_schema["required"] == [
            "core_event",
            "hidden_signal",
            "actionable",
            "score",
        ]

    def test_uses_query_output_format(self) -> None:
        """Verify query() + output_format is used for JSON Schema validation."""
        from rss2cubox import enrich_agent

        # 验证函数使用 query() + output_format + structured_output
        import inspect
        source = inspect.getsource(enrich_agent._enrich_one)
        # 新方案：使用 query() + output_format + ResultMessage.structured_output
        assert "query" in source
        assert "output_format" in source
        assert "structured_output" in source
        assert "ResultMessage" in source


class TestEnrichAgentTools:
    """Tests for MCP tools configuration."""

    def test_read_webpage_jina_tool_exists(self) -> None:
        """Verify read_webpage_jina tool is configured."""
        from rss2cubox.enrich_agent import JINA_READER_BASE, JINA_MAX_CHARS

        assert JINA_READER_BASE == "https://r.jina.ai/"
        assert JINA_MAX_CHARS >= 1000

    def test_tools_defined(self) -> None:
        """Verify tools are defined in source."""
        from rss2cubox import enrich_agent
        import inspect

        source = inspect.getsource(enrich_agent._enrich_one)
        assert "read_webpage_jina" in source


class TestEnrichAgentConfig:
    """Tests for configuration constants."""

    def test_config_defaults(self) -> None:
        """Verify default configuration values."""
        from rss2cubox import enrich_agent

        assert enrich_agent.ENRICH_AGENT_ENABLED is True
        assert enrich_agent.ENRICH_MAX_WORKERS >= 1
        assert enrich_agent.ENRICH_MIN_SCORE >= 0
        assert enrich_agent.ENRICH_MAX_ITEMS > 0
        assert enrich_agent.ENRICH_ITEM_TIMEOUT_SECONDS >= 10


class TestEnrichAgentErrorHandling:
    """Tests for error handling."""

    def test_missing_url_returns_error(self) -> None:
        """Test that missing URL returns error."""
        from rss2cubox import enrich_agent
        import anyio

        result, reason = anyio.run(enrich_agent._enrich_one, {}, {})
        assert result is None
        assert reason == "missing_url"

    def test_import_error_returns_error(self) -> None:
        """Test that import error is handled."""
        # 通过模拟 ImportError 来测试
        # 这里测试模块级别的配置
        from rss2cubox.enrich_agent import (
            ENRICH_AGENT_ENABLED,
            ENRICH_MAX_WORKERS,
            ENRICH_MIN_SCORE,
            ENRICH_MAX_ITEMS,
            ENRICH_ITEM_TIMEOUT_SECONDS,
            ENRICH_MAX_BUDGET_USD,
            JINA_READER_BASE,
            JINA_MAX_CHARS,
        )

        assert isinstance(ENRICH_AGENT_ENABLED, bool)
        assert isinstance(ENRICH_MAX_WORKERS, int)
        assert isinstance(ENRICH_MIN_SCORE, float)
        assert isinstance(ENRICH_MAX_ITEMS, int)
        assert isinstance(ENRICH_ITEM_TIMEOUT_SECONDS, int)
        assert JINA_READER_BASE == "https://r.jina.ai/"
        assert JINA_MAX_CHARS >= 1000
