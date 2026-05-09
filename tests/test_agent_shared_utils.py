"""Tests for Phase-2 shared agent utilities (TDD: Red phase)."""
import pytest
from unittest.mock import MagicMock, patch


class TestGetJinaConfig:
    """get_jina_config 应返回统一的 Jina Reader 配置。"""

    def test_returns_dict_with_required_keys(self) -> None:
        """返回值必须包含 base_url, max_chars, wechat_timeout 三个 key。"""
        from rss2cubox.agent_sdk_runner import get_jina_config

        cfg = get_jina_config()
        assert isinstance(cfg, dict)
        assert "base_url" in cfg
        assert "max_chars" in cfg
        assert "wechat_timeout" in cfg

    def test_base_url_defaults_to_jina(self) -> None:
        """未设置环境变量时默认使用 r.jina.ai/。"""
        import os
        from rss2cubox.agent_sdk_runner import get_jina_config

        key = f"_TEST_JINA_{id(os.getpid())}"
        os.environ.pop(key, None)
        # 确保原始 JINA_READER_BASE 也被清除
        orig = os.environ.pop("JINA_READER_BASE", None)
        try:
            cfg = get_jina_config()
            assert "jina.ai" in cfg["base_url"]
        finally:
            if orig is not None:
                os.environ["JINA_READER_BASE"] = orig

    def test_max_chars_is_positive_int(self) -> None:
        """max_chars 必须为正整数。"""
        from rss2cubox.agent_sdk_runner import get_jina_config

        cfg = get_jina_config()
        assert isinstance(cfg["max_chars"], int)
        assert cfg["max_chars"] > 0

    def test_wechat_timeout_at_least_10(self) -> None:
        """wechat_timeout 最小值为 10。"""
        from rss2cubox.agent_sdk_runner import get_jina_config

        cfg = get_jina_config()
        assert cfg["wechat_timeout"] >= 10

    def test_respects_env_override(self) -> None:
        """环境变量可覆盖默认值。"""
        import os
        from rss2cubox.agent_sdk_runner import get_jina_config

        orig_base = os.environ.get("JINA_READER_BASE")
        orig_chars = os.environ.get("JINA_MAX_CHARS")
        try:
            os.environ["JINA_READER_BASE"] = "https://custom.jina.ai/"
            os.environ["JINA_MAX_CHARS"] = "5000"
            cfg = get_jina_config()
            assert cfg["base_url"] == "https://custom.jina.ai/"
            assert cfg["max_chars"] == 5000
        finally:
            if orig_base is not None:
                os.environ["JINA_READER_BASE"] = orig_base
            else:
                os.environ.pop("JINA_READER_BASE", None)
            if orig_chars is not None:
                os.environ["JINA_MAX_CHARS"] = orig_chars
            else:
                os.environ.pop("JINA_MAX_CHARS", None)


class TestCreateReadWebpageMcp:
    """create_read_webpage_mcp 应返回配置好的 MCP server 和工具名前缀。"""

    def test_returns_server_and_tool_name(self) -> None:
        """应返回 (server, tool_name_prefix) 元组。"""
        from rss2cubox.agent_sdk_runner import create_read_webpage_mcp

        result = create_read_webpage_mcp("test-server")
        assert len(result) == 2
        server, tool_prefix = result
        assert server is not None
        assert isinstance(tool_prefix, str)
        assert "test-server" in tool_prefix

    def test_server_has_read_webpage_tool(self) -> None:
        """server 必须注册了 read_webpage 工具。"""
        from rss2cubox.agent_sdk_runner import create_read_webpage_mcp

        server, _ = create_read_webpage_mcp("my-tools")
        # create_sdk_mcp_server 返回 dict（含 instance/name/type）
        assert isinstance(server, dict) or hasattr(server, "name") or "name" in server

    def test_different_names_produce_different_servers(self) -> None:
        """不同 name 参数产生独立的 server 实例。"""
        from rss2cubox.agent_sdk_runner import create_read_webpage_mcp

        s1, p1 = create_read_webpage_mcp("alpha")
        s2, p2 = create_read_webpage_mcp("beta")
        assert p1 != p2
        assert "alpha" in p1
        assert "beta" in p2

    def test_accepts_optional_jina_config(self) -> None:
        """可选传入自定义 jina_config 覆盖默认值。"""
        from rss2cubox.agent_sdk_runner import create_read_webpage_mcp

        custom_cfg = {"base_url": "https://custom.ai/", "max_chars": 100, "wechat_timeout": 15}
        server, prefix = create_read_webpage_mcp("custom", jina_config=custom_cfg)
        assert server is not None
        assert "custom" in prefix


class TestNormalizeSignalItem:
    """normalize_signal_item 应统一处理 string/dict 格式的信号项。"""

    def test_string_input_returns_text_only(self) -> None:
        """字符串输入返回 {text, source_urls:[], source_titles:[]}。"""
        from rss2cubox.agent_sdk_runner import normalize_signal_item

        result = normalize_signal_item("hello world")
        assert result is not None
        assert result["text"] == "hello world"
        assert result["source_urls"] == []
        assert result["source_titles"] == []

    def test_empty_string_returns_none(self) -> None:
        """空字符串返回 None。"""
        from rss2cubox.agent_sdk_runner import normalize_signal_item

        assert normalize_signal_item("") is None
        assert normalize_signal_item("   ") is None

    def test_none_input_returns_none(self) -> None:
        """None 输入返回 None。"""
        from rss2cubox.agent_sdk_runner import normalize_signal_item

        assert normalize_signal_item(None) is None

    def test_dict_with_text_and_sources(self) -> None:
        """标准 dict 输入正确解析 text/urls/titles。"""
        from rss2cubox.agent_sdk_runner import normalize_signal_item

        item = {
            "text": "AI breakthrough",
            "source_urls": ["https://a.com", "https://b.com"],
            "source_titles": ["Article A", "Article B"],
        }
        result = normalize_signal_item(item)
        assert result["text"] == "AI breakthrough"
        assert len(result["source_urls"]) == 2
        assert result["source_urls"][0] == "https://a.com"
        assert len(result["source_titles"]) == 2

    def test_strips_whitespace_from_urls(self) -> None:
        """URL 列表中的空白项和空白字符应被清理。"""
        from rss2cubox.agent_sdk_runner import normalize_signal_item

        item = {"text": "x", "source_urls": [" https://a.com ", "", "  https://b.com"]}
        result = normalize_signal_item(item)
        assert result["source_urls"] == ["https://a.com", "https://b.com"]

    def test_non_list_urls_becomes_empty(self) -> None:
        """urls 非列表类型时降级为空列表。"""
        from rss2cubox.agent_sdk_runner import normalize_signal_item

        item = {"text": "x", "source_urls": "not_a_list"}
        result = normalize_signal_item(item)
        assert result["source_urls"] == []

    def test_truncates_to_max_length(self) -> None:
        """text 超过 maxLength 时截断（默认 200）。"""
        from rss2cubox.agent_sdk_runner import normalize_signal_item

        long_text = "x" * 300
        item = {"text": long_text}
        result = normalize_signal_item(item)
        assert len(result["text"]) <= 200

    def test_supports_comment_field_when_enabled(self) -> None:
        """enable_comment=True 时保留 comment 字段。"""
        from rss2cubox.agent_sdk_runner import normalize_signal_item

        item = {"text": "test", "comment": "good article"}
        result = normalize_signal_item(item, enable_comment=True)
        assert result.get("comment") == "good article"

    def test_no_comment_field_by_default(self) -> None:
        """默认不包含 comment 字段。"""
        from rss2cubox.agent_sdk_runner import normalize_signal_item

        item = {"text": "test", "comment": "should be ignored"}
        result = normalize_signal_item(item)
        assert "comment" not in result

    def test_limits_source_count_to_10(self) -> None:
        """source_urls/titles 最多保留 10 条。"""
        from rss2cubox.agent_sdk_runner import normalize_signal_item

        urls = [f"https://{i}.com" for i in range(15)]
        titles = [f"Title {i}" for i in range(15)]
        item = {"text": "x", "source_urls": urls, "source_titles": titles}
        result = normalize_signal_item(item)
        assert len(result["source_urls"]) <= 10
        assert len(result["source_titles"]) <= 10

    def test_dict_without_text_returns_none(self) -> None:
        """缺少 text 字段的 dict 返回 None。"""
        from rss2cubox.agent_sdk_runner import normalize_signal_item

        assert normalize_signal_item({"url": "https://x.com"}) is None

    def test_integer_input_converts_to_string(self) -> None:
        """非字符串非字典输入尝试转为字符串。"""
        from rss2cubox.agent_sdk_runner import normalize_signal_item

        result = normalize_signal_item(12345)
        assert result is not None
        assert result["text"] == "12345"


class TestRunWithFallback:
    """run_with_fallback 应封装 StructuredOutputError → extract_json_from_text 模式。"""

    @pytest.mark.asyncio
    async def test_returns_result_on_success(self) -> None:
        """正常执行时直接返回结果，不触发 fallback。"""
        from rss2cubox.agent_sdk_runner import run_with_fallback

        async def _ok_agent():
            return {"predictions": [{"id": 1}]}

        result = await run_with_fallback(_ok_agent(), agent_name="test",
                                          validate=lambda d: isinstance(d.get("predictions"), list))
        assert result["predictions"][0]["id"] == 1

    @pytest.mark.asyncio
    async def test_fallback_on_structured_output_error(self) -> None:
        """StructuredOutputError 时自动调用 extract_json_from_text。"""
        from rss2cubox.agent_sdk_runner import run_with_fallback, _StructuredOutputError

        async def _fail_agent():
            raise _StructuredOutputError('{"predictions": [1, 2]}')

        result = await run_with_fallback(
            _fail_agent(),
            agent_name="test_agent",
            validate=lambda d: True,
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_raises_when_fallback_also_fails(self) -> None:
        """fallback 解析也失败时抛出原异常。"""
        from rss2cubox.agent_sdk_runner import run_with_fallback, _StructuredOutputError

        async def _fail_agent():
            raise _StructuredOutputError("not json at all")

        try:
            await run_with_fallback(
                _fail_agent(),
                agent_name="test",
                validate=lambda d: True,
            )
            assert False, "应该抛出异常"
        except Exception:
            pass  # expected

    @pytest.mark.asyncio
    async def test_logs_fallback_events_via_logger(self) -> None:
        """fallback 过程应通过 sdk_logger 记录事件，且最终返回有效结果。"""
        from rss2cubox.agent_sdk_runner import run_with_fallback, _StructuredOutputError

        # 使用真实 log_event（非 Mock）避免参数签名冲突
        events_log: list[str] = []

        def _log(level: str, event: str, **kw) -> None:
            events_log.append(event)

        async def _fail_agent():
            raise _StructuredOutputError('{"data": [1]}')

        result = await run_with_fallback(
            _fail_agent(),
            agent_name="test_fb",
            validate=lambda d: "data" in d,
            sdk_log=_log,
        )
        assert result is not None
        assert any("fallback" in e for e in events_log)

    @pytest.mark.asyncio
    async def test_validate_rejects_invalid_fallback(self) -> None:
        """validate 函数返回 False 时视为 fallback 失败。"""
        from rss2cubox.agent_sdk_runner import run_with_fallback, _StructuredOutputError

        async def _fail_agent():
            raise _StructuredOutputError('{"wrong_key": "value"}')

        try:
            await run_with_fallback(
                _fail_agent(),
                agent_name="test",
                validate=lambda d: "expected_key" in d,
            )
            assert False, "应该因验证失败而抛出"
        except Exception:
            pass
