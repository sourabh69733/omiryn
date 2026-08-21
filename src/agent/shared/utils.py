"""Pure structural validation helpers with no agent-domain dependencies."""
from __future__ import annotations


def unknown_fields(value: dict[str, object], allowed: set[str] | frozenset[str]) -> tuple[str, ...]:
    """Return unsupported object keys in stable order."""
    return tuple(sorted(set(value) - set(allowed)))


def is_non_empty_string(value: object) -> bool:
    """Return whether a value is non-empty human text."""
    return isinstance(value, str) and bool(value.strip())


def is_number(value: object) -> bool:
    """Accept real JSON numbers while rejecting booleans."""
    return not isinstance(value, bool) and isinstance(value, (int, float))



def conversation_extraction_window(
    messages: list[dict[str, object]],
) -> dict[str, int] | None:
    """Selects bounded conversation windows for memory extraction."""
    indexes = [
        int(message["message_index"])
        for message in messages
        if isinstance(message.get("message_index"), int)
    ]
    if not indexes:
        return None
    return {
        "start_message_index": min(indexes),
        "end_message_index": max(indexes),
        "user_message_count": len(indexes),
    }
