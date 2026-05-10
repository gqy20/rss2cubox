"""Tests for global_agent module."""
import pytest


class TestGlobalAgentOutputFormat:
    """Tests for query() + text parsing (IssueLab approach)."""

    def test_output_format_schema(self) -> None:
        """Verify output_format has correct schema structure with source attribution."""
        from rss2cubox.global_agent import GLOBAL_OUTPUT_SCHEMA

        # 验证新格式：signal items 是 object 而非 string
        for field in ("trends", "weak_signals", "daily_advices"):
            item_type = GLOBAL_OUTPUT_SCHEMA["properties"][field]["items"]["type"]
            assert item_type == "object", f"{field} items should be object, got {item_type}"

        assert GLOBAL_OUTPUT_SCHEMA["required"] == [
            "trends",
            "weak_signals",
            "daily_advices",
        ]


class TestGlobalAgentTools:
    """Tests for MCP tools configuration."""

    def test_tools_configured(self) -> None:
        """Verify required tools delegate to shared get_jina_config."""
        from rss2cubox.agent_sdk_runner import get_jina_config
        from rss2cubox.global_agent import GLOBAL_AGENT_ENABLE_SKILLS

        cfg = get_jina_config()
        assert isinstance(cfg, dict)
        assert isinstance(GLOBAL_AGENT_ENABLE_SKILLS, bool)


class TestGlobalAgentPrompt:
    """Tests for system prompt."""

    def test_system_prompt_contains_key_instructions(self) -> None:
        """Verify system prompt contains key instructions."""
        from rss2cubox.global_agent import SYSTEM_PROMPT

        # 验证 prompt 不再要求调用工具
        assert "submit_insights" not in SYSTEM_PROMPT
        assert "JSON" in SYSTEM_PROMPT

    def test_system_prompt_contains_source_attribution_instruction(self) -> None:
        """Verify system prompt contains source attribution (溯源) requirements."""
        from rss2cubox.global_agent import SYSTEM_PROMPT

        assert "溯源要求" in SYSTEM_PROMPT or "source_urls" in SYSTEM_PROMPT
        assert "不要编造 URL" in SYSTEM_PROMPT or "不要编造" in SYSTEM_PROMPT

    def test_user_prompt_contains_source_attribution(self) -> None:
        """Verify user prompt includes source_urls/source_titles in output format description."""
        from rss2cubox.global_agent import _build_user_prompt

        prompt = _build_user_prompt("/tmp/signals.json", "/tmp/history.json", 10)
        assert "source_urls" in prompt
        assert "source_titles" in prompt


class TestNormalizeGlobalPayload:
    """Tests for _normalize_global_payload — payload 归一化（含溯源兼容）。"""

    def test_new_format_full_payload(self) -> None:
        """全新格式输入正常归一化"""
        from rss2cubox.global_agent import _normalize_global_payload

        payload = {
            "trends": [
                {"text": "趋势A", "source_urls": ["https://a.com"], "source_titles": ["标题A"]},
            ],
            "weak_signals": [
                {"text": "弱信号B", "source_urls": [], "source_titles": []},
            ],
            "daily_advices": [
                {"text": "建议C", "source_urls": ["https://c.com"], "source_titles": ["标题C"]},
            ],
            "key_topics": ["AI", "Agent"],
            "confidence_level": "high",
        }

        result = _normalize_global_payload(payload)

        assert len(result["trends"]) == 1
        assert result["trends"][0]["text"] == "趋势A"
        assert result["trends"][0]["source_urls"] == ["https://a.com"]
        assert len(result["weak_signals"]) == 1
        assert result["weak_signals"][0]["text"] == "弱信号B"
        assert len(result["daily_advices"]) == 1
        assert result["key_topics"] == ["AI", "Agent"]
        assert result["confidence_level"] == "high"

    def test_legacy_string_array_compatibility(self) -> None:
        """旧格式 string[] 输入自动兼容升级"""
        from rss2cubox.global_agent import _normalize_global_payload

        payload = {
            "trends": ["趋势1", "趋势2"],
            "weak_signals": ["信号1"],
            "daily_advices": ["建议1"],
        }

        result = _normalize_global_payload(payload)

        assert len(result["trends"]) == 2
        assert result["trends"][0]["text"] == "趋势1"
        assert result["trends"][0]["source_urls"] == []
        assert result["trends"][0]["source_titles"] == []
        assert len(result["weak_signals"]) == 1
        assert result["weak_signals"][0]["text"] == "信号1"

    def test_mixed_format_in_single_field(self) -> None:
        """同一字段内混合新旧格式"""
        from rss2cubox.global_agent import _normalize_global_payload

        payload = {
            "trends": [
                {"text": "新格式趋势", "source_urls": ["https://x.com"], "source_titles": ["X"]},
                "旧格式字符串趋势",
            ],
            "weak_signals": [],
            "daily_advices": [],
        }

        result = _normalize_global_payload(payload)

        assert len(result["trends"]) == 2
        assert result["trends"][0]["text"] == "新格式趋势"
        assert result["trends"][0]["source_urls"] == ["https://x.com"]
        assert result["trends"][1]["text"] == "旧格式字符串趋势"
        assert result["trends"][1]["source_urls"] == []

    def test_empty_and_invalid_items_filtered(self) -> None:
        """空值被过滤；标量类型转为字符串保留"""
        from rss2cubox.global_agent import _normalize_global_payload

        payload = {
            "trends": ["有效趋势", "", None, {"text": ""}, 42],
            "weak_signals": [],
            "daily_advices": [],
        }

        result = _normalize_global_payload(payload)

        # "有效趋势" + "42"（标量转字符串），其余被过滤
        assert len(result["trends"]) == 2
        assert result["trends"][0]["text"] == "有效趋势"
        assert result["trends"][1]["text"] == "42"

    def test_default_confidence_level(self) -> None:
        """confidence_level 缺失或非法时默认 medium"""
        from rss2cubox.global_agent import _normalize_global_payload

        assert _normalize_global_payload({})["confidence_level"] == "medium"
        assert _normalize_global_payload({"confidence_level": "invalid"})["confidence_level"] == "medium"
        assert _normalize_global_payload({"confidence_level": "low"})["confidence_level"] == "low"

    def test_key_topics_normalized_from_objects(self) -> None:
        """key_topics 支持 object 格式降级取文本"""
        from rss2cubox.global_agent import _normalize_global_payload

        payload = {
            "trends": [], "weak_signals": [], "daily_advices": [],
            "key_topics": [{"name": "AI"}, "纯字符串Topic"],
        }

        result = _normalize_global_payload(payload)

        assert result["key_topics"] == ["AI", "纯字符串Topic"]

    def test_missing_fields_default_to_empty(self) -> None:
        """缺失字段默认为空数组"""
        from rss2cubox.global_agent import _normalize_global_payload

        result = _normalize_global_payload({})

        assert result["trends"] == []
        assert result["weak_signals"] == []
        assert result["daily_advices"] == []
        assert result["key_topics"] == []


class TestGlobalAgentIntegration:
    """Integration tests for global_agent."""

    def _mock_db_calls(self, monkeypatch):
        """Mock 所有 DB 读写，避免真实连接。"""
        from rss2cubox import db_client

        monkeypatch.setattr(
            db_client, "get_all_global_insights",
            lambda limit=1000: [{"trends": [], "weak_signals": [], "daily_advices": []}],
        )
        monkeypatch.setattr(db_client, "save_global_insights", lambda payload: True)

    def test_empty_candidates_skips_analysis(self, monkeypatch) -> None:
        """Test that empty candidates skips analysis."""
        from rss2cubox import global_agent

        self._mock_db_calls(monkeypatch)

        result = global_agent.run_global_analysis(
            analyses={}, candidates=[]
        )

        assert result is None

    def test_non_empty_analyses_are_forwarded_to_global_agent(self, monkeypatch) -> None:
        from rss2cubox import global_agent

        monkeypatch.setattr(global_agent, "GLOBAL_AGENT_ENABLED", True)
        self._mock_db_calls(monkeypatch)

        captured = {"items": None}

        async def fake_run(high_value_items, history_signals, log_event=None, *, pre_fetched_texts=None):  # noqa: ANN001
            captured["items"] = high_value_items
            return {"trends": [], "weak_signals": [], "daily_advices": [], "key_topics": [], "confidence_level": "medium"}

        monkeypatch.setattr(global_agent, "_run_agent", fake_run)

        analyses = {
            "e1": {"hidden_signal": "hs", "core_event": "ce"},
            "e2": {"hidden_signal": "hs2", "core_event": "ce2"},
            "e3": {"hidden_signal": "hs3", "core_event": "ce3"},
        }
        candidates = [
            {"eid": "e1", "url": "https://example.com/1", "title": "T1"},
            {"eid": "e2", "url": "https://example.com/2", "title": "T2"},
            {"eid": "e3", "url": "https://example.com/3", "title": "T3"},
        ]

        monkeypatch.delenv("NEON_DATABASE_URL", raising=False)

        result = global_agent.run_global_analysis(analyses=analyses, candidates=candidates)

        assert result is None
        assert len(captured["items"]) == 3
        item = captured["items"][0]
        assert item["url"] == "https://example.com/1"
        assert item["title"] == "T1"
        assert item["hidden_signal"] == "hs"
        assert item["core_event"] == "ce"
        assert "importance_score" in item
        assert "key_topics" not in item or isinstance(item.get("key_topics"), list)
