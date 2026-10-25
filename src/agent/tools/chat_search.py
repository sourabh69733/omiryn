"""search_chats: the reply model looks up real lines in the user's past and uploaded chats."""

from __future__ import annotations

import os
from typing import Any

from agent.memory_engine.search import SEARCH_TOOL, search_chats_hybrid, search_note

from .registry import Tool, ToolContext, ToolResult, register_tool


def chat_search_enabled() -> bool:
    return os.getenv("AGENT_CHAT_SEARCH", "true").strip().lower() != "false"


async def _run(arguments: dict[str, Any], context: ToolContext) -> ToolResult:
    query = str(arguments.get("query") or "").strip()[:200]
    person = str(arguments.get("person") or "").strip()[:80] or None
    days = arguments.get("days")
    days = days if isinstance(days, int) and not isinstance(days, bool) and days > 0 else None
    hits = await search_chats_hybrid(str(context.user_id), query, person=person, days=days)
    return ToolResult(search_note(query, person, days, hits), {"query": query, "person": person, "days": days, "hits": len(hits)})


SEARCH_CHATS = register_tool(
    Tool(
        name=SEARCH_TOOL["function"]["name"],
        description=SEARCH_TOOL["function"]["description"],
        parameters=SEARCH_TOOL["function"]["parameters"],
        run=_run,
        enabled=lambda context: bool(context.user_id) and chat_search_enabled(),
    )
)

__all__ = ["SEARCH_CHATS", "chat_search_enabled"]
