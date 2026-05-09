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
        import anyio as _anyio

        if timeout_seconds and timeout_seconds > 0:
            with _anyio.fail_after(timeout_seconds):
                result = await _consume_query()
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
            log_event(level, event=event, stage="agent_sdk", agent=agent_name, **extra_fields, **fields)
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
