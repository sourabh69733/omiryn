"""Sets memory evidence times to when the user sent the message.

Memories extracted before evidence used the message's send time recorded the extraction time
instead, so "when did I tell you" could be off by hours or days. Each row is corrected only
when the stored quote matches the message at its index, so a shifted index is never trusted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from .conversations import get_conversation
from .database import ENGINE
from .schema import agent_memory_evidence
from .utils import _unprotect_text

# Differences below this are clock noise, not a wrong time.
_TOLERANCE = timedelta(minutes=1)


def backfill_evidence_times(*, apply: bool) -> dict[str, int]:
    """Count (and with apply=True, fix) evidence rows whose time is not the message send time."""
    counts = {"checked": 0, "fixed": 0, "already_right": 0, "no_message_time": 0, "quote_mismatch": 0}
    conversations: dict[tuple[str, str], list[dict[str, Any]]] = {}
    with ENGINE.begin() as connection:
        rows = connection.execute(select(agent_memory_evidence)).mappings().all()
    for row in rows:
        counts["checked"] += 1
        key = (row["conversation_id"], row["user_id"])
        if key not in conversations:
            conversation = get_conversation(*key)
            conversations[key] = (conversation or {}).get("messages") or []
        sent = _message_time(conversations[key], row["message_index"])
        if sent is None:
            counts["no_message_time"] += 1
            continue
        message = conversations[key][row["message_index"]]
        if not _quote_matches(_unprotect_text(row["user_id"], row["exact_quote"]), message):
            counts["quote_mismatch"] += 1
            continue
        observed = _aware(row["observed_at"])
        if abs(observed - sent) <= _TOLERANCE:
            counts["already_right"] += 1
            continue
        counts["fixed"] += 1
        if apply:
            with ENGINE.begin() as connection:
                connection.execute(
                    agent_memory_evidence.update()
                    .where(agent_memory_evidence.c.id == row["id"])
                    .values(observed_at=sent)
                )
    return counts


def _message_time(messages: list[dict[str, Any]], index: Any) -> datetime | None:
    if not isinstance(index, int) or not 0 <= index < len(messages):
        return None
    value = messages[index].get("created_at")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _quote_matches(quote: str, message: dict[str, Any]) -> bool:
    normalized = " ".join(quote.split()).casefold()
    content = " ".join(str(message.get("content") or "").split()).casefold()
    return bool(normalized) and message.get("role") == "user" and normalized in content


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


__all__ = ["backfill_evidence_times"]
