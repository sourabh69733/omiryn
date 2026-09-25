"""The companion's notes about what it said itself: opinions, tastes, jokes and promises.

These keep the companion consistent across chats ("you told me you prefer long walks") and
let it keep its promises. They are separate from user memories, whose rules forbid storing
assistant claims. Invalid items are dropped one by one; they never fail the whole batch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agent.memory_engine.processing.models import MemoryBatch
from agent.shared.timeline import parse_time
from agent.shared.utils import is_non_empty_string

SELF_NOTE_KINDS = ("opinion", "preference", "joke", "promise")
SELF_NOTE_RESOLUTIONS = ("done", "dropped")
MAX_SELF_NOTE_CHARS = 200
MAX_SELF_NOTE_CHANGES = 6


@dataclass(frozen=True)
class SelfNoteAdd:
    kind: str
    text: str
    message_index: int
    due_at: datetime | None = None


@dataclass(frozen=True)
class SelfNoteResolve:
    note_id: str
    status: str


@dataclass(frozen=True)
class SelfNoteChanges:
    adds: tuple[SelfNoteAdd, ...] = ()
    resolves: tuple[SelfNoteResolve, ...] = ()
    dropped: tuple[str, ...] = field(default=())

    @property
    def empty(self) -> bool:
        return not self.adds and not self.resolves


def validate_self_notes(
    raw: Any,
    *,
    batch: MemoryBatch,
    active_note_ids: set[str],
) -> SelfNoteChanges:
    """Keep only well-formed changes backed by the companion's own new messages."""
    if not isinstance(raw, list):
        return SelfNoteChanges()
    assistant_indexes = {
        message.message_index for message in batch.new_messages if message.role == "assistant"
    }
    adds: list[SelfNoteAdd] = []
    resolves: list[SelfNoteResolve] = []
    dropped: list[str] = []
    resolved_ids: set[str] = set()
    for item in raw[:MAX_SELF_NOTE_CHANGES]:
        operation = item.get("operation") if isinstance(item, dict) else None
        if operation == "add":
            note, reason = _add(item, assistant_indexes)
            if note:
                adds.append(note)
            else:
                dropped.append(reason)
        elif operation == "resolve":
            note_id = str(item.get("target_note_id") or "")
            status = item.get("status")
            if note_id in active_note_ids and note_id not in resolved_ids and status in SELF_NOTE_RESOLUTIONS:
                resolves.append(SelfNoteResolve(note_id, status))
                resolved_ids.add(note_id)
            else:
                dropped.append("resolve needs an active target_note_id and status done or dropped")
        else:
            dropped.append("operation must be add or resolve")
    return SelfNoteChanges(tuple(adds), tuple(resolves), tuple(dropped))


def _add(item: dict[str, Any], assistant_indexes: set[int]) -> tuple[SelfNoteAdd | None, str]:
    kind = item.get("kind")
    if kind not in SELF_NOTE_KINDS:
        return None, "kind must be opinion, preference, joke or promise"
    text = " ".join(str(item.get("text") or "").split()) if is_non_empty_string(item.get("text")) else ""
    if not text or len(text) > MAX_SELF_NOTE_CHARS:
        return None, f"text must be 1-{MAX_SELF_NOTE_CHARS} characters"
    index = item.get("message_index")
    if isinstance(index, bool) or index not in assistant_indexes:
        return None, "message_index must be a new companion message"
    due_at = parse_time(item.get("due_at")) if kind == "promise" else None
    return SelfNoteAdd(kind=kind, text=text, message_index=index, due_at=due_at), ""


__all__ = [
    "MAX_SELF_NOTE_CHARS",
    "SELF_NOTE_KINDS",
    "SelfNoteAdd",
    "SelfNoteChanges",
    "SelfNoteResolve",
    "validate_self_notes",
]
