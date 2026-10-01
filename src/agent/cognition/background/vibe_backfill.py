"""Writes a vibe card from a user's past chats, for users who chatted before vibe cards existed."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from agent.memory_engine.memories.vibe import (
    VIBE_AREAS,
    VIBE_AREA_IDS,
    merge_vibe,
    validate_vibe_updates,
    vibe_progress,
)
from agent.providers import analyze_vibe_backfill
from storage import get_vibe_card, list_conversations, update_vibe_card

# Most recent chat text sent to the model; older text is dropped first.
TRANSCRIPT_CHAR_BUDGET = 24000
MESSAGE_CHAR_LIMIT = 600


async def backfill_user_vibe(
    user_id: str,
    *,
    apply: bool = False,
    force: bool = False,
    model: str | None = None,
    timeout_seconds: float | None = 180,
) -> dict[str, Any]:
    """{"status", "areas": {area: line}, "milestone"}. Writes only with apply=True."""
    current = get_vibe_card(user_id)
    if current["areas"] and not force:
        return {"status": "has_card", "areas": {}, "milestone": current["milestone"]}
    conversations = list_conversations(user_id)
    transcript, last_sent_at = chat_transcript(conversations)
    if not transcript:
        return {"status": "no_messages", "areas": {}, "milestone": current["milestone"]}
    raw = await analyze_vibe_backfill(
        json.dumps(
            {
                "vibe_areas": [{"id": area_id, "meaning": goal} for area_id, _, goal in VIBE_AREAS],
                "current_vibe": current["areas"],
                "chats": transcript,
            },
            ensure_ascii=False,
        ),
        conversation_id=conversations[0]["id"],
        model=model,
        timeout_seconds=timeout_seconds,
    )
    updates = validate_vibe_updates(
        raw.get("vibe") if isinstance(raw, dict) else None, max_updates=len(VIBE_AREA_IDS)
    )
    milestone = vibe_progress(merge_vibe(current["areas"], updates)).milestone
    if not updates:
        return {"status": "nothing_found", "areas": {}, "milestone": milestone}
    if apply:
        # Dated to the last chat, so an old milestone is not announced as news.
        update_vibe_card(user_id, updates, now=last_sent_at)
    return {"status": "written" if apply else "would_write", "areas": updates, "milestone": milestone}


def chat_transcript(conversations: list[dict[str, Any]]) -> tuple[str, datetime | None]:
    """Chats oldest first as "user: ..." / "companion: ..." lines, trimmed to the budget."""
    lines: list[str] = []
    has_user_text = False
    last_sent_at: datetime | None = None
    for conversation in sorted(conversations, key=lambda row: row.get("created_at") or ""):
        lines.append(f"--- chat {conversation['id'][:8]} ---")
        for message in conversation.get("messages") or []:
            role = message.get("role")
            text = " ".join(str(message.get("content") or "").split())
            if role not in {"user", "assistant"} or not text or message.get("delivery_status") == "failed":
                continue
            has_user_text = has_user_text or role == "user"
            speaker = "user" if role == "user" else "companion"
            lines.append(f"{speaker}: {text[:MESSAGE_CHAR_LIMIT]}")
            sent_at = _parse_time(message.get("created_at"))
            if sent_at and (last_sent_at is None or sent_at > last_sent_at):
                last_sent_at = sent_at
    if not has_user_text:
        return "", None
    kept: list[str] = []
    used = 0
    for line in reversed(lines):
        used += len(line) + 1
        if used > TRANSCRIPT_CHAR_BUDGET:
            break
        kept.append(line)
    return "\n".join(reversed(kept)), last_sent_at


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


__all__ = ["backfill_user_vibe", "chat_transcript"]
