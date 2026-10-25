"""Tools the reply model can call. Importing this package registers every built-in tool.

A new tool is one module: a handler that returns a ToolResult and a register_tool call, imported here.
"""

from . import chat_search as _chat_search  # noqa: F401  (registers search_chats)
from . import web_search as _web_search  # noqa: F401  (registers web_search)
from . import places as _places  # noqa: F401  (registers find_places)
from .chat_search import chat_search_enabled
from .loop import MAX_CALLS_PER_ROUND, MAX_ROUNDS, reply_with_tools, tool_arguments, tools_enabled
from .places import places_enabled
from .registry import Tool, ToolCall, ToolContext, ToolResult, get_tool, register_tool, run_calls, tool_specs
from .web_search import web_search_enabled

__all__ = [
    "MAX_CALLS_PER_ROUND",
    "MAX_ROUNDS",
    "Tool",
    "ToolCall",
    "ToolContext",
    "ToolResult",
    "chat_search_enabled",
    "get_tool",
    "places_enabled",
    "register_tool",
    "reply_with_tools",
    "run_calls",
    "tool_arguments",
    "tool_specs",
    "tools_enabled",
    "web_search_enabled",
]
