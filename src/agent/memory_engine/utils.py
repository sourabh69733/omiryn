from __future__ import annotations


def conversation_extraction_window(
    messages: list[dict[str, object]],
) -> dict[str, int] | None:
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
