"""show_app_page: the reply model puts a button under its reply that opens a page of the app.

Asked to end a reply with a hidden page marker, the model added it when the whole reply was the
page ("show me my privacy page") but almost never after answering a privacy question in words. A
tool call it makes reliably; code then puts the button on the reply (steps/draft.py).
"""

from __future__ import annotations

from typing import Any

from agent.context_engine.policy.replies import APP_PAGES

from .registry import Tool, ToolContext, ToolResult, register_tool

_NAMES = {"privacy": "Privacy", "memories": "Memories", "vibe": "Vibe", "matches": "Matches", "profile": "Profile"}


async def _run(arguments: dict[str, Any], context: ToolContext) -> ToolResult:
    page = str(arguments.get("page") or "").strip().lower()
    if page not in APP_PAGES:
        return ToolResult(f"There is no {page or 'such'} page. Pages: {', '.join(APP_PAGES)}.", {"page": None})
    return ToolResult(
        f"A button to their {_NAMES[page]} page will show under your reply. Now reply in words as usual; "
        "do not paste a link or describe the button.",
        {"page": page},
    )


SHOW_APP_PAGE = register_tool(
    Tool(
        name="show_app_page",
        description=(
            "Put a button under your reply that opens a page of the Omiryn app. Use it when they ask about "
            "privacy or the privacy policy (privacy), what you remember about them (memories), their vibe "
            "(vibe), their matches (matches) or their profile (profile), or ask to see one of these."
        ),
        parameters={
            "type": "object",
            "properties": {"page": {"type": "string", "enum": list(APP_PAGES), "description": "The page to open."}},
            "required": ["page"],
        },
        run=_run,
        timeout_seconds=2.0,
    )
)


def shown_page(tool_calls: list[dict[str, Any]]) -> str | None:
    """The last page a show_app_page call in this turn's trace asked for."""
    pages = [call.get("page") for call in tool_calls if call.get("tool") == SHOW_APP_PAGE.name and call.get("page")]
    return pages[-1] if pages else None


__all__ = ["SHOW_APP_PAGE", "shown_page"]
