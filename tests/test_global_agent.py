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

    def test_uses_query_output_format(self) -> None:
        """Verify query() + output_format is used for JSON Schema validation."""
        from rss2cubox import agent_sdk_runner, global_agent
        import inspect

        global_source = inspect.getsource(global_agent._run_agent)
        runner_source = inspect.getsource(agent_sdk_runner.run_json_agent)
        assert "run_json_agent" in global_source
        assert "query" in runner_source
        assert "output_format" in runner_source
        assert "structured_output" in runner_source
        assert "ResultMessage" in runner_source


class TestGlobalAgentTools:
    """Tests for MCP tools configuration."""

    def test_tools_configured(self) -> None:
        """Verify required tools are configured."""
        from rss2cubox.global_agent import (
            JINA_READER_BASE,
            JINA_MAX_CHARS,
            GLOBAL_AGENT_ENABLE_SKILLS,
            WECHAT_FETCH_TIMEOUT_SECONDS,
        )

        assert JINA_READER_BASE == "https://r.jina.ai/"
        assert JINA_MAX_CHARS >= 1000
        assert isinstance(GLOBAL_AGENT_ENABLE_SKILLS, bool)
        assert WECHAT_FETCH_TIMEOUT_SECONDS >= 10

    def test_tools_in_run_agent(self) -> None:
        """Verify tools are defined in _run_agent."""
        from rss2cubox import global_agent
        import inspect

        source = inspect.getsource(global_agent._run_agent)
        assert "read_webpage" in source
        assert "read_webpage_text" in source
        # 使用内置 Read 工具，不再需要 read_signals_file MCP 工具
        assert "mcp__insights-tools__read_webpage" in source


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


class TestGlobalAgentConfig:
    """Tests for configuration constants."""

    def test_config_defaults(self) -> None:
        """Verify default configuration values."""
        from rss2cubox.global_agent import (
            GLOBAL_AGENT_ENABLE_SKILLS,
            JINA_READER_BASE,
            JINA_MAX_CHARS,
            WECHAT_FETCH_TIMEOUT_SECONDS,
        )

        assert isinstance(GLOBAL_AGENT_ENABLE_SKILLS, bool)
        assert JINA_READER_BASE == "https://r.jina.ai/"
        assert JINA_MAX_CHARS >= 1000
        assert WECHAT_FETCH_TIMEOUT_SECONDS >= 10


class TestNormalizeSignalItem:
    """Tests for _normalize_signal_item — 单条信号归一化（含溯源格式）。"""

    def test_new_format_full(self) -> None:
        """新格式完整输入：text + source_urls + source_titles"""
        from rss2cubox.global_agent import _normalize_signal_item

        result = _normalize_signal_item({
            "text": "多模态推理成为新战场",
            "source_urls": ["https://example.com/a", "https://example.com/b"],
            "source_titles": ["文章A标题", "文章B标题"],
        })

        assert result is not None
        assert result["text"] == "多模态推理成为新战场"
        assert result["source_urls"] == ["https://example.com/a", "https://example.com/b"]
        assert result["source_titles"] == ["文章A标题", "文章B标题"]

    def test_new_format_text_only(self) -> None:
        """新格式只有 text，urls/titles 为空"""
        from rss2cubox.global_agent import _normalize_signal_item

        result = _normalize_signal_item({"text": "纯文本结论"})

        assert result is not None
        assert result["text"] == "纯文本结论"
        assert result["source_urls"] == []
        assert result["source_titles"] == []

    def test_legacy_string_format(self) -> None:
        """旧格式：纯字符串自动包装为新结构"""
        from rss2cubox.global_agent import _normalize_signal_item

        result = _normalize_signal_item("旧格式的纯文本趋势")

        assert result is not None
        assert result["text"] == "旧格式的纯文本趋势"
        assert result["source_urls"] == []
        assert result["source_titles"] == []

    def test_empty_string_returns_none(self) -> None:
        """空字符串返回 None"""
        from rss2cubox.global_agent import _normalize_signal_item

        assert _normalize_signal_item("") is None
        assert _normalize_signal_item("   ") is None

    def test_none_input_returns_none(self) -> None:
        """None / 非法类型返回 None"""
        from rss2cubox.global_agent import _normalize_signal_item

        assert _normalize_signal_item(None) is None
        assert _normalize_signal_item(123) is None
        assert _normalize_signal_item([]) is None

    def test_dict_without_text_returns_none(self) -> None:
        """dict 缺少 text 字段返回 None"""
        from rss2cubox.global_agent import _normalize_signal_item

        assert _normalize_signal_item({"source_urls": ["https://x.com"]}) is None

    def test_urls_titles_truncated_to_equal_length(self) -> None:
        """urls 和 titles 数量不一致时截断为等长"""
        from rss2cubox.global_agent import _normalize_signal_item

        result = _normalize_signal_item({
            "text": "test",
            "source_urls": ["https://a.com", "https://b.com", "https://c.com"],
            "source_titles": ["标题A"],  # 只有 1 个 title
        })

        assert result is not None
        assert len(result["source_urls"]) == 1
        assert len(result["source_titles"]) == 1
        assert result["source_urls"][0] == "https://a.com"

    def test_urls_titles_max_10_items(self) -> None:
        """超过 10 条时截断"""
        from rss2cubox.global_agent import _normalize_signal_item

        urls = [f"https://example.com/{i}" for i in range(15)]
        titles = [f"标题{i}" for i in range(15)]

        result = _normalize_signal_item({
            "text": "test",
            "source_urls": urls,
            "source_titles": titles,
        })

        assert result is not None
        assert len(result["source_urls"]) == 10
        assert len(result["source_titles"]) == 10

    def test_non_string_urls_filtered_out(self) -> None:
        """非字符串 URL 被过滤"""
        from rss2cubox.global_agent import _normalize_signal_item

        result = _normalize_signal_item({
            "text": "test",
            "source_urls": ["https://valid.com", 123, None, "", "  "],
            "source_titles": ["有效标题", "也该被过滤"],
        })

        assert result is not None
        assert result["source_urls"] == ["https://valid.com"]
        # titles 也截断到与 urls 等长
        assert len(result["source_titles"]) == 1

    def test_text_truncated_to_200_chars(self) -> None:
        """text 超过 200 字符时截断"""
        from rss2cubox.global_agent import _normalize_signal_item

        long_text = "好" * 300
        result = _normalize_signal_item({"text": long_text})

        assert result is not None
        assert len(result["text"]) == 200


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
        """空值和非法条目被过滤掉"""
        from rss2cubox.global_agent import _normalize_global_payload

        payload = {
            "trends": ["有效趋势", "", None, {"text": ""}, 42],
            "weak_signals": [],
            "daily_advices": [],
        }

        result = _normalize_global_payload(payload)

        assert len(result["trends"]) == 1
        assert result["trends"][0]["text"] == "有效趋势"

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


class TestGlobalOutputSchema:
    """Tests for GLOBAL_OUTPUT_SCHEMA — 新版带溯源的 Schema 结构。"""

    def test_schema_top_level_structure(self) -> None:
        """顶层为 object，包含 trends/weak_signals/daily_advices/key_topics/confidence_level"""
        from rss2cubox.global_agent import GLOBAL_OUTPUT_SCHEMA

        assert GLOBAL_OUTPUT_SCHEMA["type"] == "object"
        props = GLOBAL_OUTPUT_SCHEMA["properties"]
        assert "trends" in props
        assert "weak_signals" in props
        assert "daily_advices" in props
        assert "key_topics" in props
        assert "confidence_level" in props

    def test_signal_fields_are_object_arrays(self) -> None:
        """trends/weak_signals/daily_advices 的 items 是 object 类型（非 string）"""
        from rss2cubox.global_agent import GLOBAL_OUTPUT_SCHEMA

        for field in ("trends", "weak_signals", "daily_advices"):
            item_schema = GLOBAL_OUTPUT_SCHEMA["properties"][field]["items"]
            assert item_schema["type"] == "object", f"{field} items should be object, got {item_schema['type']}"

    def test_signal_item_has_text_required(self) -> None:
        """signal item 包含必填 text 字段"""
        from rss2cubox.global_agent import GLOBAL_OUTPUT_SCHEMA

        for field in ("trends", "weak_signals", "daily_advices"):
            item_props = GLOBAL_OUTPUT_SCHEMA["properties"][field]["items"]["properties"]
            assert "text" in item_props
            assert "text" in GLOBAL_OUTPUT_SCHEMA["properties"][field]["items"]["required"]

    def test_signal_item_has_optional_source_fields(self) -> None:
        """signal item 包含可选的 source_urls 和 source_titles"""
        from rss2cubox.global_agent import GLOBAL_OUTPUT_SCHEMA

        for field in ("trends", "weak_signals", "daily_advices"):
            item_props = GLOBAL_OUTPUT_SCHEMA["properties"][field]["items"]["properties"]
            assert "source_urls" in item_props
            assert "source_titles" in item_props
            # 不在 required 中
            required = GLOBAL_OUTPUT_SCHEMA["properties"][field]["items"].get("required", [])
            assert "source_urls" not in required
            assert "source_titles" not in required

    def test_source_urls_is_uri_array_with_max_limit(self) -> None:
        """source_urls 是 URI 数组且有 maxItems 限制"""
        from rss2cubox.global_agent import GLOBAL_OUTPUT_SCHEMA

        item_props = GLOBAL_OUTPUT_SCHEMA["properties"]["trends"]["items"]["properties"]
        url_schema = item_props["source_urls"]["items"]
        assert url_schema["type"] == "string"
        assert item_props["source_urls"]["maxItems"] == 10

    def test_source_titles_is_string_array_with_max_limit(self) -> None:
        """source_titles 是字符串数组且有 maxLength 和 maxItems 限制"""
        from rss2cubox.global_agent import GLOBAL_OUTPUT_SCHEMA

        item_props = GLOBAL_OUTPUT_SCHEMA["properties"]["trends"]["items"]["properties"]
        title_schema = item_props["source_titles"]["items"]
        assert title_schema["type"] == "string"
        assert item_props["source_titles"]["maxItems"] == 10

    def test_text_has_max_length(self) -> None:
        """text 字段有 maxLength 限制"""
        from rss2cubox.global_agent import GLOBAL_OUTPUT_SCHEMA

        item_props = GLOBAL_OUTPUT_SCHEMA["properties"]["trends"]["items"]["properties"]
        assert item_props["text"]["maxLength"] == 200

    def test_confidence_level_enum(self) -> None:
        """confidence_level 只允许 high/medium/low"""
        from rss2cubox.global_agent import GLOBAL_OUTPUT_SCHEMA

        conf = GLOBAL_OUTPUT_SCHEMA["properties"]["confidence_level"]
        assert conf["enum"] == ["high", "medium", "low"]

    def test_required_fields_at_top_level(self) -> None:
        """顶层 required 只包含三个 signal 字段"""
        from rss2cubox.global_agent import GLOBAL_OUTPUT_SCHEMA

        assert set(GLOBAL_OUTPUT_SCHEMA["required"]) == {"trends", "weak_signals", "daily_advices"}


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

    def test_non_empty_analyses_are_forwarded_to_global_agent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from rss2cubox import global_agent

        monkeypatch.setattr(global_agent, "GLOBAL_AGENT_ENABLED", True)

        captured = {"items": None}

        async def fake_run(high_value_items, history_signals):  # noqa: ANN001
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


class TestExtractJsonFromText:
    """Tests for extract_json_from_text fallback JSON extraction."""

    def test_pure_json(self) -> None:
        from rss2cubox.agent_sdk_runner import extract_json_from_text

        text = '{"trends": [{"text": "test"}], "weak_signals": [], "daily_advices": []}'
        result = extract_json_from_text(text)
        assert result is not None
        assert result["trends"][0]["text"] == "test"

    def test_markdown_code_block(self) -> None:
        from rss2cubox.agent_sdk_runner import extract_json_from_text

        text = '分析结果如下：\n\n```json\n{"trends": [{"text": "hello"}]}\n```\n\n以上是结论。'
        result = extract_json_from_text(text)
        assert result is not None
        assert result["trends"][0]["text"] == "hello"

    def test_code_block_without_json_label(self) -> None:
        from rss2cubox.agent_sdk_runner import extract_json_from_text

        text = '```\n{"key": "value"}\n```'
        result = extract_json_from_text(text)
        assert result is not None
        assert result["key"] == "value"

    def test_prefixed_text_with_brace_extraction(self) -> None:
        from rss2cubox.agent_sdk_runner import extract_json_from_text

        text = '这是分析报告：\n{"trends": [{"text": "趋势1"}], "weak_signals": []}\n结束。'
        result = extract_json_from_text(text)
        assert result is not None
        assert len(result["trends"]) == 1

    def test_empty_input(self) -> None:
        from rss2cubox.agent_sdk_runner import extract_json_from_text

        assert extract_json_from_text("") is None
        assert extract_json_from_text(None) is None  # type: ignore[arg-type]
        assert extract_json_from_text("   ") is None
        assert extract_json_from_text("no json here") is None

    def test_nested_objects_preserved(self) -> None:
        from rss2cubox.agent_sdk_runner import extract_json_from_text

        text = '{"trends": [{"text": "t", "source_urls": ["https://a.com"], "source_titles": ["A"]}]}'
        result = extract_json_from_text(text)
        assert result is not None
        assert result["trends"][0]["source_urls"] == ["https://a.com"]
        assert result["trends"][0]["source_titles"] == ["A"]

    def test_realistic_model_output_format(self) -> None:
        from rss2cubox.agent_sdk_runner import extract_json_from_text

        # 模拟 glm-5v-turbo 的实际输出格式：前缀文字 + json 代码块
        text = """基于已读取的情报，输出分析报告：

```json
{
  "trends": [
    {
      "text": "中端模型能力跃升",
      "source_urls": ["https://example.com/1"],
      "source_titles": ["文章标题"]
    }
  ],
  "weak_signals": [],
  "daily_advices": [],
  "key_topics": ["AI"],
  "confidence_level": "high"
}
```

以上为本次分析结果。"""
        result = extract_json_from_text(text)
        assert result is not None
        assert result["trends"][0]["text"] == "中端模型能力跃升"
        assert result["confidence_level"] == "high"
        assert len(result["key_topics"]) == 1
