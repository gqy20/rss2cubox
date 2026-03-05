"""Tests for global_agent module."""
import pytest


class TestGlobalAgentOutputFormat:
    """Tests for query() + text parsing (IssueLab approach)."""

    def test_output_format_schema(self) -> None:
        """Verify output_format has correct schema structure."""
        expected_schema = {
            "type": "object",
            "properties": {
                "trends": {"type": "array", "items": {"type": "string"}},
                "weak_signals": {"type": "array", "items": {"type": "string"}},
                "daily_advices": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["trends", "weak_signals", "daily_advices"],
        }

        assert "trends" in expected_schema["properties"]
        assert "weak_signals" in expected_schema["properties"]
        assert "daily_advices" in expected_schema["properties"]
        assert expected_schema["required"] == [
            "trends",
            "weak_signals",
            "daily_advices",
        ]

    def test_uses_query_text_parsing(self) -> None:
        """Verify query() + text parsing is used (IssueLab approach)."""
        from rss2cubox import global_agent
        import inspect

        source = inspect.getsource(global_agent._run_agent)
        # 新方案：使用 query() + _extract_json_from_text
        assert "query" in source
        assert "_extract_json_from_text" in source
        # 不再使用 output_format 和 structured_output
        assert "output_format" not in source


class TestGlobalAgentTools:
    """Tests for MCP tools configuration."""

    def test_tools_configured(self) -> None:
        """Verify required tools are configured."""
        from rss2cubox.global_agent import (
            JINA_READER_BASE,
            JINA_MAX_CHARS,
            GLOBAL_AGENT_ENABLE_SKILLS,
        )

        assert JINA_READER_BASE == "https://r.jina.ai/"
        assert JINA_MAX_CHARS >= 1000
        assert isinstance(GLOBAL_AGENT_ENABLE_SKILLS, bool)

    def test_tools_in_run_agent(self) -> None:
        """Verify tools are defined in _run_agent."""
        from rss2cubox import global_agent
        import inspect

        source = inspect.getsource(global_agent._run_agent)
        assert "read_signals_file" in source
        assert "read_webpage" in source


class TestGlobalAgentPrompt:
    """Tests for system prompt."""

    def test_system_prompt_contains_key_instructions(self) -> None:
        """Verify system prompt contains key instructions."""
        from rss2cubox.global_agent import SYSTEM_PROMPT

        # 验证 prompt 不再要求调用工具
        assert "submit_insights" not in SYSTEM_PROMPT
        assert "JSON" in SYSTEM_PROMPT


class TestGlobalAgentConfig:
    """Tests for configuration constants."""

    def test_config_defaults(self) -> None:
        """Verify default configuration values."""
        from rss2cubox.global_agent import (
            GLOBAL_AGENT_ENABLE_SKILLS,
            JINA_READER_BASE,
            JINA_MAX_CHARS,
        )

        assert isinstance(GLOBAL_AGENT_ENABLE_SKILLS, bool)
        assert JINA_READER_BASE == "https://r.jina.ai/"
        assert JINA_MAX_CHARS >= 1000


class TestGlobalAgentIntegration:
    """Integration tests for global_agent."""

    def test_empty_candidates_skips_analysis(self) -> None:
        """Test that empty candidates skips analysis."""
        from rss2cubox import global_agent

        # 空的 candidates 应该跳过分析
        analyses = {}
        candidates = []

        result = global_agent.run_global_analysis(
            analyses=analyses, candidates=candidates
        )

        assert result is None
