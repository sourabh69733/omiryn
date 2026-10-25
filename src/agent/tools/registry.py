"""The tools the reply model can call: each one is a spec the model reads plus a handler code runs.

A tool registers itself once. A turn asks which tools are on for this user (`tool_specs`), and code
runs whatever the model called (`run_calls`): every call in a message, at the same time, each with
its own time limit. A tool that fails or is unknown gives the model a short note instead of an
error, so a broken tool never breaks a reply.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True)
class ToolContext:
    user_id: str | None
    conversation_id: str | None = None


@dataclass(frozen=True)
class ToolResult:
    """note: what the model reads next. trace: short facts for the turn trace (no user content)."""

    note: str
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[[dict[str, Any], ToolContext], Awaitable[ToolResult]]
    enabled: Callable[[ToolContext], bool] = lambda context: True
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def spec(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


_TOOLS: dict[str, Tool] = {}


def register_tool(tool: Tool) -> Tool:
    _TOOLS[tool.name] = tool
    return tool


def get_tool(name: str) -> Tool | None:
    return _TOOLS.get(name)


def tool_specs(context: ToolContext) -> list[dict[str, Any]]:
    """Specs of the tools that are on for this turn, in the order they were registered."""
    return [tool.spec() for tool in _TOOLS.values() if _is_enabled(tool, context)]


async def run_calls(calls: list[ToolCall], context: ToolContext) -> list[ToolResult]:
    """Runs the calls at the same time; results come back in the order of the calls."""
    return list(await asyncio.gather(*(_run_one(call, context) for call in calls)))


async def _run_one(call: ToolCall, context: ToolContext) -> ToolResult:
    tool = _TOOLS.get(call.name)
    if tool is None or not _is_enabled(tool, context):
        return ToolResult(f'There is no tool called "{call.name}". Answer without it.', {"tool": call.name, "ok": False, "error": "unknown_tool"})
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(tool.run(call.arguments, context), timeout=tool.timeout_seconds)
        ok, error = True, None
    except asyncio.TimeoutError:
        result, ok, error = ToolResult(f"{tool.name} took too long and returned nothing. Do not guess its answer."), False, "timeout"
    except Exception as failure:
        logger.warning("agent.tools.failed tool=%s error_type=%s", tool.name, type(failure).__name__)
        result, ok, error = ToolResult(f"{tool.name} failed and returned nothing. Do not guess its answer."), False, type(failure).__name__
    trace = {"tool": tool.name, "ok": ok, "ms": round((time.perf_counter() - started) * 1000), **result.trace}
    if error:
        trace["error"] = error
    return ToolResult(result.note, trace)


def _is_enabled(tool: Tool, context: ToolContext) -> bool:
    try:
        return bool(tool.enabled(context))
    except Exception:
        return False


__all__ = ["Tool", "ToolCall", "ToolContext", "ToolResult", "get_tool", "register_tool", "run_calls", "tool_specs"]
