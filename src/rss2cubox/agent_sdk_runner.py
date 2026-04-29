"""Shared Claude Agent SDK JSON runner."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable


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
    cwd: Path | None = None,
    setting_sources: list[str] | None = None,
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
    try:
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
                if message.is_error:
                    raise RuntimeError(message.subtype or "agent_error")
                raise RuntimeError(message.subtype or "no_structured_output")
    except Exception as exc:
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
