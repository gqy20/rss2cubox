"""Shared Claude Agent SDK JSON runner."""
from __future__ import annotations

import asyncio
import json
import os
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


# ── 可诊断性：stderr 尾部 + 异常分类（模式取自 TrendPluse）────
# CLI 子进程的 stderr 是排查「Command failed with exit code 1」的唯一线索，
# 但默认只打终端、不进事件流。这里留最近 N 行，出错时拼进异常消息。
_STDERR_TAIL_LINES = 20


def _make_stderr_capture():
    """返回 (缓冲列表, 可给 ClaudeAgentOptions.stderr 的回调)。"""
    lines = []
    seen = set()

    def _handle(message):
        stripped = message.strip() if isinstance(message, str) else str(message).strip()
        if not stripped:
            return
        if stripped in seen:
            return
        seen.add(stripped)
        lines.append(stripped)
        if len(lines) > _STDERR_TAIL_LINES:
            del lines[: len(lines) - _STDERR_TAIL_LINES]

    return lines, _handle


def _classify_sdk_exception(exc):
    """把 SDK 调用的异常归类为稳定类别，用于日志过滤与统计。"""
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, _StructuredOutputError):
        return "structured_output_error"
    if isinstance(exc, ValueError):
        return "validation_error"

    message = str(exc).lower()
    if "error_max_structured_output_retries" in message:
        return "structured_output_retries_exhausted"
    if "exit code" in message or "command failed" in message:
        return "process_error"
    if "canceled" in message or "cancelled" in message:
        return "cancelled"
    if "rate" in message and "limit" in message:
        return "rate_limit"
    return "unknown"


def _stderr_tail(lines):
    return " | ".join(lines[-_STDERR_TAIL_LINES:]) if lines else ""


def _enriched_error(exc, stderr_lines):
    """把 stderr 尾部拼进异常消息，让「exit code 1」不再是死胡同。

    始终返回 Exception（早期版本返回字符串，raise 字符串是 TypeError，
    只有被外层 RuntimeError 包裹时才碰巧能用）。
    """
    msg = str(exc) or type(exc).__name__
    tail = _stderr_tail(stderr_lines)
    if tail:
        msg = f"{msg}; stderr_tail={tail}"
    enriched = RuntimeError(msg)
    if isinstance(exc, BaseException):
        enriched.__cause__ = exc
    return enriched


# 可重试的异常。error_max_structured_output_retries 跑 30 分钟后零产出全损，
# 没有外层重试就是彻底白跑。RuntimeError 覆盖 CLI 的各种进程级失败。
RETRYABLE_SDK_ERRORS = (
    TimeoutError,
    _StructuredOutputError,
    RuntimeError,
)


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
        from claude_agent_sdk import (  # type: ignore
    AssistantMessage,
    ClaudeAgentOptions,
    RateLimitEvent,
    ResultMessage,
    StreamEvent,
    TaskNotificationMessage,
    TaskProgressMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)
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
    # 结构化输出自校正重试上限（CLI 原生环境变量，默认 5）：
    # schema 校验失败时模型会看到具体错误并自我修正，上限耗尽才报
    # error_max_structured_output_retries。经 options.env 传给 CLI 子进程。
    if "MAX_STRUCTURED_OUTPUT_RETRIES" not in _resolved_env:
        _resolved_env["MAX_STRUCTURED_OUTPUT_RETRIES"] = (
            os.getenv("AGENT_SDK_MAX_STRUCTURED_OUTPUT_RETRIES", "5")
        )

    stderr_lines, stderr_capture = _make_stderr_capture()
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=allowed_tools or [],
        mcp_servers=mcp_servers,
        permission_mode=permission_mode,
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        cwd=cwd or Path.cwd(),
        setting_sources=setting_sources,
        stderr=(lambda line: (stderr_capture(line), stderr(line) if stderr else None)),
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
                    except (RuntimeError, Exception):
                        pass
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
    tool_call_count = 0
    # tool_use_id → tool 名称映射：UserMessage 里的 ToolResultBlock 只有 id，
    # 没有工具名，需要从 AssistantMessage 的 ToolUseBlock 里建立映射
    tool_names: dict[str, str] = {}

    async def _consume_query():
        nonlocal saw_message, tool_call_count
        # 消费契约（SDK client.py 的注释点名了这个问题）：async for 循环体
        # raise/return 不会关闭生成器（PEP 533 被推迟），悬空的生成器会被
        # 事件循环的 finalizer 在任意时刻异步 aclose（实测发生在重试的
        # asyncio.sleep 期间），其 finally: await query.close() 杀子进程时
        # 触发 anyio cancel scope 取消，毒死后续尝试。
        # 所以：循环体内只记录，绝不 raise/return；迭代到自然耗尽（生成器
        # 自己跑完 finally），循环外再抛。超时取消路径用 detached task 兑底。
        failure: Any = None          # is_error=True 的 ResultMessage
        result: Any = None           # 正常的 ResultMessage
        output: Any = None           # structured_output
        raw_text = ""
        cli_query = query(prompt=prompt, options=options, transport=transport)
        try:
            async for message in cli_query:
                if not saw_message:
                    saw_message = True
                    emit(
                        "agent_sdk_first_message",
                        duration_ms=int((time.perf_counter() - query_started_at) * 1000),
                        total_duration_ms=int((time.perf_counter() - started_at) * 1000),
                        message_type=type(message).__name__,
                    )

                # ── 中间消息：可观测性的主体 ──
                # 之前只处理 ResultMessage，工具调用/思考/限流完全不可见，排查
                # 「CLI exit 1 但拿不到任何信息」只能靠写一次性诊断脚本。
                if isinstance(message, AssistantMessage):
                    for block in (getattr(message, "content", None) or []):
                        block_type = type(block).__name__
                        if block_type == "ToolUseBlock":
                            tool_call_count += 1
                            block_id = getattr(block, "id", "") or ""
                            block_name = getattr(block, "name", "") or ""
                            if block_id:
                                tool_names[block_id] = block_name
                            emit(
                                "agent_sdk_tool_use",
                                tool=block_name,
                                tool_use_id=block_id,
                                tool_input=json.dumps(
                                    getattr(block, "input", {}),
                                    ensure_ascii=False,
                                    default=str,
                                )[:200],
                                call_index=tool_call_count,
                            )
                        elif block_type == "ToolResultBlock":
                            content = getattr(block, "content", None)
                            content_str = ""
                            if isinstance(content, list):
                                for part in content:
                                    if type(part).__name__ == "TextBlock":
                                        content_str = (getattr(part, "text", "") or "")[:200]
                                        break
                            elif isinstance(content, str):
                                content_str = content[:200]
                            emit(
                                "agent_sdk_tool_result",
                                tool_use_id=getattr(block, "tool_use_id", ""),
                                is_error=bool(getattr(block, "is_error", False)),
                                content=content_str,
                            )
                        elif block_type == "ThinkingBlock":
                            thinking = (getattr(block, "thinking", "") or "")[:300]
                            if thinking:
                                emit("agent_sdk_thinking", thinking=thinking)
                elif isinstance(message, UserMessage):
                    # 工具结果（含 StructuredOutput 的校验反馈）走 UserMessage。
                    # 之前完全不处理，模型结构化输出失败 5 次时我们看不到
                    # 任何一条「Output does not match required schema: …」反馈，
                    # 只能盲猜它为什么重试。
                    content = getattr(message, "content", None)
                    if isinstance(content, list):
                        for block in content:
                            if type(block).__name__ == "ToolResultBlock":
                                block_content = getattr(block, "content", None)
                                content_str = ""
                                if isinstance(block_content, list):
                                    for part in block_content:
                                        if type(part).__name__ == "TextBlock":
                                            content_str = (getattr(part, "text", "") or "")[:300]
                                            break
                                elif isinstance(block_content, str):
                                    content_str = block_content[:300]
                                emit(
                                    "agent_sdk_tool_result",
                                    tool=tool_names.get(getattr(block, "tool_use_id", ""), ""),
                                    tool_use_id=getattr(block, "tool_use_id", ""),
                                    is_error=bool(getattr(block, "is_error", False)),
                                    content=content_str,
                                )
                elif isinstance(message, RateLimitEvent):
                    emit(
                        "agent_sdk_rate_limit",
                        retry_after_ms=getattr(message, "retry_after_ms", None),
                    )
                elif isinstance(message, (TaskProgressMessage, TaskNotificationMessage)):
                    emit(
                        "agent_sdk_task_update",
                        message_type=type(message).__name__,
                        payload=str(message)[:200],
                    )
                # StreamEvent 量大，只在需要极细粒度调试时才考虑记

                if isinstance(message, ResultMessage):
                    # usage / model_usage 必须记下来：total_cost_usd 是 CLI 按它自己的
                    # Claude 定价表算的，走第三方网关时那个金额不代表真实账单。
                    # 真实成本 = token 数 × 网关单价，没有 usage 就算不出来。
                    emit(
                        "agent_sdk_result",
                        duration_ms=int((time.perf_counter() - query_started_at) * 1000),
                        total_duration_ms=int((time.perf_counter() - started_at) * 1000),
                        tool_calls=tool_call_count,
                        is_error=message.is_error,
                        subtype=message.subtype,
                        has_structured_output=message.structured_output is not None,
                        num_turns=getattr(message, "num_turns", None),
                        total_cost_usd=getattr(message, "total_cost_usd", None),
                        usage=getattr(message, "usage", None),
                        model_usage=getattr(message, "model_usage", None),
                        stop_reason=getattr(message, "stop_reason", None),
                        session_id=getattr(message, "session_id", None),
                        errors=getattr(message, "errors", None),
                    )
                    # 只记录，不在这里抛：ResultMessage 通常是流里最后一条，
                    # 迭代会自然结束、生成器自己走完 teardown。
                    output = message.structured_output
                    raw_text = getattr(message, "result", None) or ""
                    if message.is_error:
                        failure = message
                    else:
                        result = message

        except asyncio.CancelledError:
            # 超时路径（wait_for 取消）：当前任务已取消，无法在本任务 await
            # aclose——把 teardown 交给独立任务确定性执行，避免生成器被
            # 事件循环 finalizer 在任意时刻异步关闭（那会毒化事件循环）。
            close_task = asyncio.ensure_future(cli_query.aclose())
            close_task.add_done_callback(
                lambda t: t.exception() if not t.cancelled() else None
            )
            raise
        # 循环自然耗尽（生成器已在同任务内完成 finally: query.close()）。
        # 现在才抛异常/返回——安全。
        if failure is not None:
            # errors 数组里是「Failed to provide valid structured output
            # after N attempts」这类具体信息，并入异常而不是只报 subtype
            detail = "; ".join(getattr(failure, "errors", None) or [])
            exc = RuntimeError(failure.subtype or "agent_error")
            if detail:
                exc = RuntimeError(f"{failure.subtype or 'agent_error'}: {detail}")
            raise _enriched_error(exc, stderr_lines)
        if result is not None and output is not None:
            return output
        if result is not None:
            raise _StructuredOutputError(raw_text, result.subtype or "no_structured_output")
        raise RuntimeError("no_result")

    try:
        if timeout_seconds and timeout_seconds > 0:
            result = await asyncio.wait_for(_consume_query(), timeout=timeout_seconds)
        else:
            result = await _consume_query()
        return result
    except TimeoutError as exc:
        emit(
            "agent_sdk_error",
            duration_ms=int((time.perf_counter() - query_started_at) * 1000),
            total_duration_ms=int((time.perf_counter() - started_at) * 1000),
            error=f"TimeoutError after {timeout_seconds}s",
            timeout_seconds=int(timeout_seconds) if timeout_seconds else None,
        )
        raise


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


def _agent_timeout(env_key: str, *, default: float = 300, minimum: float = 30) -> float | None:
    """从环境变量解析 agent 超时秒数。

    - 未设置 → 返回 default
    - 值为 "0" 或负数 → 返回 None（禁用超时）
    - 值低于 minimum → clamp 到 minimum
    """
    import os as _os

    raw = _os.environ.get(env_key, "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
        if val <= 0:
            return None
        return max(val, minimum)
    except (ValueError, TypeError):
        return default


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


def write_temp_jsonl(rows: list[Any], *, suffix: str = ".jsonl") -> str:
    """每行一个 JSON 对象写入临时文件，返回路径（调用方负责清理）。

    用 JSONL 而不是一整个 JSON 数组，是为了让 agent 能用 Grep 按行精确定位
    单条记录、用 Read 的 offset/limit 分页，而不必把整个文件拉进上下文。
    """
    import tempfile

    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8")
    for row in rows:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
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
    max_attempts: int = 2,
    retry_delay_seconds: float = 5.0,
) -> dict[str, Any]:
    """执行 Agent 并自动处理 StructuredOutputError fallback 解析与可重试错误。

    三层容错：
    1. 正常结果直接返回
    2. Schema 验证失败时尝试 extract_json_from_text 提取 JSON（原有行为）
    3. 可重试异常（timeout / 结构化输出失败 / CLI 进程错误）整体重试

    第 3 层是后加的：实测一次 cluster 调用跑 30 分钟后
    error_max_structured_output_retries、零产出全损 —— 没有外层重试，
    一次瞬态失败就把整轮工作作废。max_attempts 默认 2，够处理瞬态问题
    又不至于把运行时间翻太多倍。
    """
    logger = make_sdk_logger(agent_name, log_event=sdk_log)

    async def _one_attempt():
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

    last_exc = None
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            return await _one_attempt()
        except RETRYABLE_SDK_ERRORS as exc:
            last_exc = exc
            category = _classify_sdk_exception(exc)
            if attempt >= max(1, max_attempts):
                logger(
                    f"{agent_name}_retries_exhausted",
                    attempts=max(1, max_attempts),
                    category=category,
                    error=str(exc)[:300],
                )
                break
            logger(
                f"{agent_name}_retrying",
                attempt=attempt,
                next_attempt=attempt + 1,
                max_attempts=max_attempts,
                category=category,
                wait_seconds=retry_delay_seconds,
                error=str(exc)[:200],
            )
            await asyncio.sleep(retry_delay_seconds)
        # 非可重试异常直接抛出
    assert last_exc is not None
    raise last_exc
