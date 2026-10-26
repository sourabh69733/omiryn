"""What Omi said before: open promises, plus opinions this message touches."""

from __future__ import annotations

from typing import Any

from agent.config import agent_pipeline_config
from agent.memory_engine.memories.ranking import text_relevance
from agent.shared.clock import utc_now
from agent.shared.timeline import date_label, parse_time, relative_day, user_zone
from storage import get_user_timezone, list_active_self_notes

SELF_NOTES_SOURCE_TYPE = "agent_self_notes"
# Open promises always show; opinions, tastes and jokes only when the message touches them.
SELF_NOTE_PROMISE_LIMIT = 4
SELF_NOTE_TOPIC_LIMIT = 5
_SELF_NOTE_RELEVANCE_FLOOR = 0.12


def self_note_sources(user_id: str | None, user_text: str) -> list[dict[str, Any]]:
    """What the companion said before: open promises, plus opinions this message touches."""
    if not user_id or agent_pipeline_config().memory_contract_version != 3:
        return []
    notes = list_active_self_notes(user_id)
    promises = [note for note in notes if note["kind"] == "promise"][:SELF_NOTE_PROMISE_LIMIT]
    scored = sorted(
        (
            (text_relevance(user_text, note["text"]), note)
            for note in notes
            if note["kind"] != "promise"
        ),
        key=lambda item: -item[0],
    )
    topical = [note for score, note in scored if score >= _SELF_NOTE_RELEVANCE_FLOOR]
    chosen = promises + topical[:SELF_NOTE_TOPIC_LIMIT]
    if not chosen:
        return []
    zone = user_zone(get_user_timezone(user_id))
    today = utc_now().astimezone(zone).date()
    lines = [
        "Things you said to this user before. Stay consistent with these opinions unless you "
        "have a reason to change your mind, and keep your promises.",
    ]
    for note in chosen:
        due = parse_time(note.get("due_at"))
        when = ""
        if due:
            local = due.astimezone(zone)
            when = f" (due {date_label(local)}, {relative_day(local.date(), today)})"
        lines.append(f"- {note['kind']}: {note['text']}{when}")
    return [
        {
            "source_type": SELF_NOTES_SOURCE_TYPE,
            "title": "Things you said before",
            "content": "\n".join(lines),
            "metadata": {"note_ids": [note["id"] for note in chosen]},
        }
    ]


__all__ = ["SELF_NOTES_SOURCE_TYPE", "self_note_sources"]
