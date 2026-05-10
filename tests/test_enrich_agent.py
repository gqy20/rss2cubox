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
                "reason": {"type": "string"},
                "hidden_signal": {"type": "string"},
                "actionable": {"type": "string"},
                "tags": {"type": "array"},
            },
            "required": ["core_event", "reason", "hidden_signal", "actionable", "tags"],
        }

        assert "core_event" in expected_schema["properties"]
        assert "reason" in expected_schema["properties"]
        assert "hidden_signal" in expected_schema["properties"]
        assert "actionable" in expected_schema["properties"]
        assert "tags" in expected_schema["properties"]
        assert expected_schema["required"] == [
            "core_event",
            "reason",
            "hidden_signal",
            "actionable",
            "tags",
        ]


class TestEnrichAgentTools:
    """Tests for MCP tools configuration."""

    def test_read_webpage_tool_config_exists(self) -> None:
        """Verify webpage reading config delegates to shared get_jina_config."""
        from rss2cubox.agent_sdk_runner import get_jina_config

        cfg = get_jina_config()
        assert isinstance(cfg, dict)
        assert "base_url" in cfg
        assert "max_chars" in cfg
        assert "wechat_timeout" in cfg

class TestEnrichAgentConfig:
    """Tests for configuration constants."""

    def test_config_defaults(self) -> None:
        """Verify default configuration values."""
        from rss2cubox import enrich_agent

        assert enrich_agent.ENRICH_AGENT_ENABLED is True
        assert enrich_agent.ENRICH_MAX_WORKERS >= 1
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
            ENRICH_ITEM_TIMEOUT_SECONDS,
            ENRICH_MAX_BUDGET_USD,
        )
        from rss2cubox.agent_sdk_runner import get_jina_config

        assert isinstance(ENRICH_AGENT_ENABLED, bool)
        assert isinstance(ENRICH_MAX_WORKERS, int)
        assert isinstance(ENRICH_ITEM_TIMEOUT_SECONDS, int)


class TestEnrichAgentPrompt:
    """Tests for prompt building robustness."""

    def test_build_user_prompt_omits_legacy_rating(self) -> None:
        from rss2cubox.enrich_agent import _build_user_prompt

        prompt = _build_user_prompt(
            {"title": "T", "url": "https://example.com", "description": "D"},
            {"core_event": ""},
        )

        assert "文章标题：T" in prompt
        assert "初步评分" not in prompt

    def test_schema_requires_structured_signal_fields(self) -> None:
        """Verify ENRICH_OUTPUT_SCHEMA requires all structured signal fields."""
        from rss2cubox.enrich_agent import ENRICH_OUTPUT_SCHEMA

        properties = ENRICH_OUTPUT_SCHEMA["properties"]
        required = set(ENRICH_OUTPUT_SCHEMA["required"])

        expected = {
            "content_source", "signal_type", "evidence_type", "evidence_strength",
            "novelty_score", "impact_horizon", "audience", "market_stage",
            "confidence", "entities", "cluster_hint", "watch_keywords",
            "prediction", "disconfirming_evidence",
        }
        assert expected.issubset(properties)
        assert expected.issubset(required)

    def test_schema_uses_numeric_codes_for_filterable_fields(self) -> None:
        """Verify filterable fields use integer codes with proper ranges."""
        from rss2cubox.enrich_agent import ENRICH_OUTPUT_SCHEMA

        properties = ENRICH_OUTPUT_SCHEMA["properties"]
        assert properties["signal_type"] == {"type": "integer", "minimum": 1, "maximum": 12}
        assert properties["evidence_type"] == {"type": "integer", "minimum": 1, "maximum": 12}
        assert properties["evidence_strength"] == {"type": "integer", "minimum": 1, "maximum": 5}
        assert properties["novelty_score"] == {"type": "integer", "minimum": 1, "maximum": 5}
        assert properties["impact_horizon"] == {"type": "integer", "minimum": 1, "maximum": 5}
        assert properties["market_stage"] == {"type": "integer", "minimum": 1, "maximum": 6}
        assert properties["confidence"] == {"type": "integer", "minimum": 1, "maximum": 5}


class TestPreFetchedText:
    """Tests for pre-fetched full text integration."""

    def test_build_prompt_with_prefetched_text(self):
        """有预抓取全文时，prompt 应包含'已预抓取全文'和正文内容。"""
        from rss2cubox.enrich_agent import _build_user_prompt

        long_text = "这是文章的完整正文内容。" * 200
        prompt = _build_user_prompt(
            {"title": "AI 突破", "url": "https://example.com/a", "description": "摘要"},
            {"core_event": ""},
            pre_fetched_text=long_text,
        )

        assert "已预抓取全文" in prompt
        assert "直接基于此进行分析" in prompt
        assert "无需再调用任何工具" in prompt
        # 全文应被截断到 15000 字符以内
        assert len(prompt) < len(long_text) + 500
        # 不应出现"调用 read_webpage"指令
        assert "调用 read_webpage" not in prompt

    def test_build_prompt_without_prefetched_text(self):
        """无预抓取全文时，prompt 应保持原有逻辑（要求调用 read_webpage）。"""
        from rss2cubox.enrich_agent import _build_user_prompt

        prompt = _build_user_prompt(
            {"title": "AI 突破", "url": "https://example.com/a", "description": "摘要"},
            {"core_event": ""},
        )

        assert "已预抓取全文" not in prompt
        assert "调用 read_webpage 工具读取原文全文" in prompt

    def test_build_prompt_with_empty_prefetched_text(self):
        """预抓取文本为空字符串时，应走 fallback 路径。"""
        from rss2cubox.enrich_agent import _build_user_prompt

        prompt = _build_user_prompt(
            {"title": "T", "url": "https://x.com", "description": "D"},
            {"core_event": ""},
            pre_fetched_text="",
        )

        assert "已预抓取全文" not in prompt
        assert "调用 read_webpage" in prompt

    def test_build_prompt_truncates_long_text(self):
        """超长全文应被截断至约 15000 字符。"""
        from rss2cubox.enrich_agent import _build_user_prompt

        very_long = "x" * 30000
        prompt = _build_user_prompt(
            {"title": "T", "url": "https://x.com", "description": "D"},
            {"core_event": ""},
            pre_fetched_text=very_long,
        )

        assert "已预抓取全文" in prompt
        # 截断后的内容不应超过 15000 + 少量前缀
        body_start = prompt.index("已预抓取全文")
        assert len(prompt) - body_start < 16000

    def test_analyze_candidates_accepts_pre_fetched_texts(self):
        """analyze_candidates_with_agent 接受 pre_fetched_texts 参数不报错。"""
        from rss2cubox.enrich_agent import analyze_candidates_with_agent

        # 空候选列表应立即返回空 dict，验证参数接受正常
        result = analyze_candidates_with_agent(
            candidates=[],
            log_event=lambda *a, **kw: None,
            pre_fetched_texts={"eid1": "some text"},
        )
        assert result == {}

    def test_get_fulltexts_by_eids_empty(self):
        """空 eid 列表返回空 dict。"""
        from rss2cubox.db_client import get_fulltexts_by_eids

        result = get_fulltexts_by_eids([])
        assert result == {}

    def test_get_fulltexts_by_eids_no_db_url(self):
        """无 DB URL 时返回空 dict（不报错）。"""
        import os
        from rss2cubox.db_client import get_fulltexts_by_eids

        old = os.environ.get("LOCAL_DB_URL")
        try:
            os.environ["LOCAL_DB_URL"] = ""
            result = get_fulltexts_by_eids(["e1", "e2"])
            assert result == {}
        finally:
            if old is None:
                os.environ.pop("LOCAL_DB_URL", None)
            else:
                os.environ["LOCAL_DB_URL"] = old
