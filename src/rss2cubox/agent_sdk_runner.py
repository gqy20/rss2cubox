"""Shared Claude Agent SDK JSON runner."""
from __future__ import annotations

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
) -> dict[str, Any]:
    try:
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query  # type: ignore
    except ImportError as exc:
        raise RuntimeError("claude_agent_sdk_import_error") from exc

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

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            if message.structured_output is not None:
                return message.structured_output
            if message.is_error:
                raise RuntimeError(message.subtype or "agent_error")
            raise RuntimeError(message.subtype or "no_structured_output")

    raise RuntimeError("no_result")
