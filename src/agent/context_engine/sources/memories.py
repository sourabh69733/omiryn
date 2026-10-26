"""Durable memories for a reply: how the user asked to be talked to, and facts about them with dates."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent.context_engine.policy.requests import HOW_TO_TALK_SOURCE_TYPE
from agent.memory_engine.memories import BROAD_RECALL_MEMORY_LIMIT, retrieve_agent_memories_for_reply
from agent.memory_engine.memories.focus import focus_state
from agent.shared.clock import utc_now
from agent.shared.timeline import date_label, parse_time, relative_day, user_zone
from storage import get_user_timezone

AGENT_MEMORIES_V3_SOURCE_TYPE = "agent_memories_v3"


def memory_sources(
    user_id: str | None,
    user_text: str,
    query_embedding: dict[str, Any] | None = None,
    *,
    broad: bool = False,
) -> list[dict[str, Any]]:
    if not user_id:
        return []
    memories = retrieve_agent_memories_for_reply(
        user_id,
        user_text,
        query_embedding=query_embedding,
        broad=broad,
        **({"limit": BROAD_RECALL_MEMORY_LIMIT} if broad else {}),
    )
    if not memories:
        return []
    style = [memory for memory in memories if memory.get("kind") == "procedural"]
    facts = [memory for memory in memories if memory.get("kind") != "procedural"]
    return how_to_talk_sources(style) + (memory_facts_sources(user_id, facts) if facts else [])


def how_to_talk_sources(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not memories:
        return []
    lines = ["How the user asked you to talk to them, in earlier chats. Follow it unless they change it."]
    lines.extend(f"- {memory_sentence(memory)}" for memory in memories)
    return [
        {
            "source_type": HOW_TO_TALK_SOURCE_TYPE,
            "title": "How to talk to the user",
            "content": "\n".join(lines),
            "metadata": {
                "memory_count": len(memories),
                "memory_ids": [memory.get("id") for memory in memories],
                "memory_kinds": [memory.get("kind") for memory in memories],
            },
        }
    ]


def memory_facts_sources(user_id: str, memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    zone = user_zone(get_user_timezone(user_id))
    lines = [
        "Relevant durable memories about the user themselves, never about other people they mention.",
        "Use only when helpful; do not quote them as a list or say you have stored notes.",
        "Memories about relationships describe lived history, not a desired partner trait.",
        "Dates carry their distance from today in brackets; use that wording (e.g. 'this Friday, "
        "in 2 days') rather than repeating the user's older relative words.",
        "Do not present past events as current. 'told you' is when the user said it.",
    ]
    for memory in memories:
        lines.append(f"- {memory_sentence(memory)}{memory_time_note(memory, zone)}")
    return [
        {
            "source_type": AGENT_MEMORIES_V3_SOURCE_TYPE,
            "title": "Relevant durable memories",
            "content": "\n".join(lines),
            "metadata": {
                "memory_count": len(memories),
                "memory_ids": [memory.get("id") for memory in memories],
                "memory_kinds": [memory.get("kind") for memory in memories],
            },
        }
    ]


def memory_sentence(memory: dict[str, Any]) -> str:
    """The memory as plain text: its stored sentence, else a readable key and value."""
    statement = str(memory.get("statement") or "").strip()
    if statement:
        return statement
    key = _readable_key(memory.get("key"))
    value = _readable_value(memory.get("value"))
    return f"{key}: {value}" if key else value


def _readable_key(key: Any) -> str:
    text = " ".join(str(key or "").replace("_", " ").replace(".", " ").split())
    return text[:1].upper() + text[1:]


def _readable_value(value: Any) -> str:
    if isinstance(value, dict):
        return "; ".join(
            f"{_readable_key(name).lower()}: {_readable_value(item)}"
            for name, item in value.items()
            if item not in (None, "", [], {})
        )
    if isinstance(value, list):
        return ", ".join(_readable_value(item) for item in value)
    return str(value)


def memory_time_note(memory: dict[str, Any], zone: Any, now: datetime | None = None) -> str:
    """Give the model event, mention and expiry dates in the user's timezone, each with its
    distance from today computed in code ("in 2 days"), so it never has to re-anchor
    relative words like "next Friday" itself."""
    today = (now or utc_now()).astimezone(zone).date()

    def dated(moment: datetime) -> str:
        local = moment.astimezone(zone)
        return f"{date_label(local)} ({relative_day(local.date(), today)})"

    notes = []
    mentions = sorted(
        {
            parsed.astimezone(zone)
            for evidence in memory.get("evidence") or []
            if (parsed := parse_time(evidence.get("observed_at")))
        }
    )
    if mentions:
        told = f"told you {dated(mentions[0])}"
        if mentions[-1].date() != mentions[0].date():
            told += f", again {dated(mentions[-1])}"
        notes.append(told)
    if event := parse_time(memory.get("occurred_at")):
        upcoming = event.astimezone(zone).date() > today
        notes.append(f"{'happens' if upcoming else 'happened'} {dated(event)}")
    if valid_until := parse_time(memory.get("valid_until")):
        notes.append(f"valid until {dated(valid_until)}")
    state = focus_state(memory, now or utc_now())
    if state == "current":
        notes.append("a current focus of theirs")
    elif state == "fading":
        notes.append("a focus they have not mentioned for weeks: it may be over, so do not assume it is still going or ask about it")
    return f" ({'; '.join(notes)})" if notes else ""


__all__ = ["AGENT_MEMORIES_V3_SOURCE_TYPE", "how_to_talk_sources", "memory_facts_sources", "memory_sentence", "memory_sources", "memory_time_note"]
