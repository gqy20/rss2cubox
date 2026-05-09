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
        env=env or {},
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
