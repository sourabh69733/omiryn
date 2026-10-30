"""Keeps private people out of queries that leave Omiryn (web search, places).

The tool descriptions already tell the model not to put names in a query. This is the code check
behind that: the names code knows (the user's own, and the people in their uploaded chats) are
facts; a query holding one is not sent, and the model is told to search without it.
"""

from __future__ import annotations

import re

from .registry import ToolContext, ToolResult

_MIN_NAME_CHARS = 3


def private_names(context: ToolContext) -> set[str]:
    """Lower-case name words of the user and of the people in their uploaded chats."""
    if not context.user_id:
        return set()
    from storage import get_user_profile
    from storage.upload_digests import list_upload_digests

    names: list[str] = []
    profile = get_user_profile(context.user_id) or {}
    names.append(str(profile.get("display_name") or ""))
    names.extend(str(stored.get("partner_name") or "") for stored in list_upload_digests(context.user_id))
    return {word.casefold() for name in names for word in re.findall(r"\w+", name) if len(word) >= _MIN_NAME_CHARS}


def named_person(query: str, names: set[str]) -> str | None:
    """The first private name word the query holds, or None."""
    words = {word.casefold() for word in re.findall(r"\w+", query)}
    found = sorted(words & names)
    return found[0] if found else None


def blocked_for_privacy(tool: str, query: str, context: ToolContext) -> ToolResult | None:
    """A note for the model instead of the call, when the query names a private person."""
    name = named_person(query, private_names(context))
    if name is None:
        return None
    return ToolResult(
        f'You called {tool} with a query that names a person the user knows ("{name}"). That query was not '
        "sent: never put private people's names or the user's own details in an outside search. Answer "
        "without it, or search again for the general thing (a place, a topic) without the name.",
        {"blocked": "private_name"},
    )


__all__ = ["blocked_for_privacy", "named_person", "private_names"]
