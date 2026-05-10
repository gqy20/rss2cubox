"""Shared Claude Agent SDK JSON runner."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable


class _StructuredOutputError(RuntimeError):
    """Schema 验证失败时抛出，携带原始输出文本供 fallback 解析。"""

    def __init__(self, raw_text: str, reason: str = ""):
        self.raw_text = raw_text
        super().__init__(reason)


def extract_json_from_text(text: str) -> dict | list | None:
    """从可能包含前缀文字或 markdown 代码块的文本中提取 JSON。"""
    if not text or not isinstance(text, str):
        return None
    # 策略1：查找 ```json ... ``` 代码块
    code_block_match = re.search(r"```(?:json)?\s*\n(.*?)\n\s*```", text, re.DOTALL)
    if code_block_match:
        candidate = code_block_match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    # 策略2：查找最外层 { ... } 或 [ ... ]
    for open_ch, close_ch in [("{", "}"), ("[", "]")]:
        start = text.find(open_ch)
        if start < 0:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == open_ch:
                depth += 1
            elif text[i] == close_ch:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    return None


async def run_json_agent(
    *,
    prompt: str,
    system_prompt: str,
    schema: dict[str, Any],
    allowed_tools: list[str] | None = None,
    mcp_servers: dict[str, Any] | None = None,
    permission_mode: str = "acceptEdits",
    max_turns: int = 20,
    max_budget_usd: float | None = None,
    timeout_seconds: float | None = None,
    cwd: Path | None = None,
    setting_sources: list[str] | None = ["project"],
    stderr: Callable[[str], None] | None = None,
    env: dict[str, str] | None = None,
    sdk_log: Callable[..., None] | None = None,
) -> dict[str, Any]:
    try:
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query  # type: ignore
    except ImportError as exc:
        raise RuntimeError("claude_agent_sdk_import_error") from exc

    started_at = time.perf_counter()

    def emit(event: str, **fields: Any) -> None:
        if sdk_log is None:
            return
        try:
            sdk_log(event, **fields)
        except TypeError:
            sdk_log(event)  # type: ignore[misc]

    _resolved_env = dict(env) if env else {}
    if "CLAUDE_CONFIG_DIR" not in _resolved_env:
        _enrich_session_dir = (cwd or Path.cwd()).parent / "logs" / "enrich-sessions"
        _enrich_session_dir.mkdir(parents=True, exist_ok=True)
        _resolved_env["CLAUDE_CONFIG_DIR"] = str(_enrich_session_dir)

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=allowed_tools or [],
        mcp_servers=mcp_servers,
        permission_mode=permission_mode,
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        cwd=cwd or Path.cwd(),
        setting_sources=setting_sources,
        stderr=stderr,
        output_format={"type": "json_schema", "schema": schema},
        env=_resolved_env,
    )

    transport = None
    if sdk_log is not None:
        try:
            from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport  # type: ignore

            class InstrumentedSubprocessCLITransport(SubprocessCLITransport):  # type: ignore[misc, valid-type]
                def __init__(self, *args: Any, **kwargs: Any) -> None:
                    super().__init__(*args, **kwargs)
                    self._write_count = 0

                async def connect(self) -> None:
                    connect_started_at = time.perf_counter()
                    emit("agent_sdk_connect_start")
                    try:
                        await super().connect()
                    except Exception as exc:
                        emit(
                            "agent_sdk_connect_error",
                            duration_ms=int((time.perf_counter() - connect_started_at) * 1000),
                            error=str(exc),
                        )
                        raise
                    emit(
                        "agent_sdk_connect_done",
                        duration_ms=int((time.perf_counter() - connect_started_at) * 1000),
                    )

                async def write(self, data: str) -> None:
                    self._write_count += 1
                    write_index = self._write_count
                    write_started_at = time.perf_counter()
                    emit(
                        "agent_sdk_write_start",
                        write_index=write_index,
                        bytes=len(data.encode("utf-8")),
                    )
                    try:
                        await super().write(data)
                    except Exception as exc:
                        emit(
                            "agent_sdk_write_error",
                            write_index=write_index,
                            duration_ms=int((time.perf_counter() - write_started_at) * 1000),
                            error=str(exc),
                        )
                        raise
                    emit(
                        "agent_sdk_write_done",
                        write_index=write_index,
                        duration_ms=int((time.perf_counter() - write_started_at) * 1000),
                    )

                async def close(self) -> None:
                    close_started_at = time.perf_counter()
                    emit("agent_sdk_close_start")
                    try:
                        await super().close()
                    finally:
                        emit(
                            "agent_sdk_close_done",
                            duration_ms=int((time.perf_counter() - close_started_at) * 1000),
                        )

            transport = InstrumentedSubprocessCLITransport(prompt=prompt, options=options)
        except Exception as exc:
            emit("agent_sdk_instrumentation_disabled", error=str(exc))

    query_started_at = time.perf_counter()
    emit("agent_sdk_query_start")
    saw_message = False

    async def _consume_query():
        nonlocal saw_message
        async for message in query(prompt=prompt, options=options, transport=transport):
            if not saw_message:
                saw_message = True
                emit(
                    "agent_sdk_first_message",
                    duration_ms=int((time.perf_counter() - query_started_at) * 1000),
                    total_duration_ms=int((time.perf_counter() - started_at) * 1000),
                    message_type=type(message).__name__,
                )
            if isinstance(message, ResultMessage):
                emit(
                    "agent_sdk_result",
                    duration_ms=int((time.perf_counter() - query_started_at) * 1000),
                    total_duration_ms=int((time.perf_counter() - started_at) * 1000),
                    is_error=message.is_error,
                    subtype=message.subtype,
                    has_structured_output=message.structured_output is not None,
                )
                if message.structured_output is not None:
                    return message.structured_output
                raw_result = getattr(message, "result", None) or ""
                if message.is_error:
                    raise RuntimeError(message.subtype or "agent_error")
                raise _StructuredOutputError(raw_result, message.subtype or "no_structured_output")

    try:
        import asyncio as _asyncio

        if timeout_seconds and timeout_seconds > 0:
            result = await _asyncio.wait_for(_consume_query(), timeout=timeout_seconds)
        else:
            result = await _consume_query()
        return result
    except TimeoutError as exc:
        emit(
            "agent_sdk_error",
            duration_ms=int((time.perf_counter() - query_started_at) * 1000),
            total_duration_ms=int((time.perf_counter() - started_at) * 1000),
            error=str(exc),
        )
        raise

    emit(
        "agent_sdk_no_result",
        duration_ms=int((time.perf_counter() - query_started_at) * 1000),
        total_duration_ms=int((time.perf_counter() - started_at) * 1000),
    )
    raise RuntimeError("no_result")


# ── Shared utility factories (TDD Green phase) ──────────────────────────────


def make_sdk_logger(agent_name: str, log_event: Any | None, **extra_fields: Any) -> Callable[..., None] | None:
    """返回参数化的 sdk_logger 闭包，或 log_event=None 时返回 no-op。

    返回的闭包签名: logger(event: str, **fields) -> None
    自动填充 stage="agent_sdk", agent=agent_name, 以及 extra_fields。
    默认级别 INFO；事件名以 _error 或 _failed 结尾或等于 agent_sdk_no_result 时记为 WARN。
    """
    if log_event is None:

        def _noop(_event: str, **_fields: Any) -> None:
            return

        return _noop

    def _logger(event: str, **fields: Any) -> None:
        level = "WARN" if event.endswith(("_error", "_failed")) or event == "agent_sdk_no_result" else "INFO"
        try:
            log_event(level, event, stage="agent_sdk", agent=agent_name, **extra_fields, **fields)
        except TypeError:
            log_event(level, event)

    return _logger


def make_stderr_logger(prefix: str, limit: int = 60) -> tuple[list[str], Callable[[str], None]]:
    """返回 (lines, log_fn) 元组，用于捕获 stderr 输出。

    lines: 累积的非空行列表（超过 limit 时从头部丢弃旧行）。
    log_fn: 可调用对象，每行会打印 [prefix] cli_stderr: {text}。
    """
    lines: list[str] = []

    def _log(line: str) -> None:
        text = str(line).strip()
        if not text:
            return
        lines.append(text)
        if len(lines) > limit:
            del lines[: len(lines) - limit]
        print(f"[{prefix}] cli_stderr: {text}", flush=True)

    return lines, _log


def _budget(name: str, default: float) -> float | None:
    """从环境变量解析预算值。未设置或空字符串时返回 default 对应的 None 语义。"""
    import os as _os

    raw = _os.environ.get(name, "")
    if not raw.strip():
        return None
    try:
        return float(raw.strip())
    except (ValueError, TypeError):
        return None


# ── Phase-2 shared utilities (TDD Green phase) ────────────────────────────


def get_jina_config() -> dict[str, Any]:
    """返回统一的 Jina Reader 配置字典。

    优先从环境变量读取，使用安全的默认值和下限。
    """
    import os as _os

    return {
        "base_url": _os.getenv("JINA_READER_BASE", "https://r.jina.ai/").strip(),
        "max_chars": max(1000, int(_os.getenv("JINA_MAX_CHARS", "30000"))),
        "wechat_timeout": max(10, int(_os.getenv("WECHAT_FETCH_TIMEOUT_SECONDS", "30"))),
    }


def create_read_webpage_mcp(
    server_name: str,
    *,
    jina_config: dict[str, Any] | None = None,
) -> tuple[Any, str]:
    """创建带 read_webpage 工具的 MCP server，返回 (server, tool_prefix)。

    server_name: 用于生成 MCP server name 和工具名前缀（如 "enrich-tools" → "mcp__enrich-tools__read_webpage"）。
    jina_config: 可选自定义 Jina 配置，默认调用 get_jina_config()。
    """
    cfg = jina_config or get_jina_config()

    try:
        from claude_agent_sdk import create_sdk_mcp_server, tool  # type: ignore
    except ImportError:
        raise RuntimeError("claude_agent_sdk_import_error")

    from rss2cubox.webpage_reader import read_webpage_text

    @tool(
        "read_webpage",
        "读取指定 URL 的正文（优先 Jina Reader 返回 Markdown；Jina 被拦截时自动降级到 Playwright 浏览器渲染）",
        {"url": str},
    )
    async def read_webpage(args: dict) -> dict:
        url = args["url"]

        def _fetch() -> tuple[bool, str]:
            ok, content, _source = read_webpage_text(
                url,
                jina_reader_base=cfg["base_url"],
                jina_max_chars=cfg["max_chars"],
                wechat_timeout_seconds=cfg["wechat_timeout"],
            )
            return ok, content

        import anyio as _anyio2
        ok, content = await _anyio2.to_thread.run_sync(_fetch)
        if not ok:
            content = f"[网页读取失败] {content}"
        return {"content": [{"type": "text", "text": content}]}

    server = create_sdk_mcp_server(
        name=server_name,
        version="1.0.0",
        tools=[read_webpage],
    )
    return server, f"mcp__{server_name}__read_webpage"


def write_temp_json(data: Any, *, suffix: str = ".json") -> str:
    """将数据写入临时 JSON 文件，返回文件路径（调用方负责清理）。"""
    import tempfile

    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8")
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.close()
    return f.name


def cleanup_temp_files(*paths: str) -> None:
    """安全删除临时文件，忽略不存在或权限错误。"""
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except Exception:
            pass


def normalize_signal_item(item: Any, *, enable_comment: bool = False, max_text_length: int = 200) -> dict[str, Any] | None:
    """归一化单条信号项，兼容 string 和 dict 格式。

    string 输入 → {text, source_urls:[], source_titles:[]}
    dict 输入 → 解析 text/source_urls/source_titles，可选保留 comment 字段。
    """
    if isinstance(item, str):
        text = item.strip()
        if not text:
            return None
        result: dict[str, Any] = {
            "text": text[:max_text_length],
            "source_urls": [],
            "source_titles": [],
        }
        if enable_comment:
            result["comment"] = ""
        return result

    if item is None:
        return None

    if not isinstance(item, dict):
        text = str(item).strip()
        if not text:
            return None
        result: dict[str, Any] = {
            "text": text[:max_text_length],
            "source_urls": [],
            "source_titles": [],
        }
        if enable_comment:
            result["comment"] = ""
        return result

    text = str(item.get("text", "")).strip()
    if not text:
        return None

    urls = item.get("source_urls", [])
    titles = item.get("source_titles", [])

    if isinstance(urls, list):
        urls = [str(u).strip() for u in urls if isinstance(u, str) and u.strip()]
    else:
        urls = []

    if isinstance(titles, list):
        titles = [str(t).strip() for t in titles if isinstance(t, str) and t.strip()]
    else:
        titles = []

    max_urls = min(len(urls), 10)
    max_titles = min(len(titles), 10)
    result = {
        "text": text[:max_text_length],
        "source_urls": urls[:max_urls],
        "source_titles": titles[:max_titles],
    }
    if enable_comment:
        comment = str(item.get("comment", "")).strip()
        result["comment"] = comment[:200] if comment else ""
    return result


async def run_with_fallback(
    coro: Any,
    *,
    agent_name: str,
    validate: Callable[[dict[str, Any]], bool],
    sdk_log: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """执行 Agent 并自动处理 StructuredOutputError fallback 解析。

    正常结果直接返回；Schema 验证失败时尝试 extract_json_from_text 提取 JSON，
    通过 validate 回调校验提取结果是否可用。
    """
    logger = make_sdk_logger(agent_name, log_event=sdk_log)
    try:
        _actual = coro() if callable(coro) else coro
        result = await _actual
        return result
    except _StructuredOutputError as e:
        logger(f"{agent_name}_fallback_start")
        fallback = extract_json_from_text(e.raw_text)
        if isinstance(fallback, dict) and validate(fallback):
            logger(f"{agent_name}_fallback_ok")
            return fallback
        logger(f"{agent_name}_fallback_failed", raw_preview=e.raw_text[:300])
        raise
