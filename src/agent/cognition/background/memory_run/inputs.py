"""What the memory run's model reads besides the new messages: the existing memories most related to
them (with how often and when the user said each), Omi's open self notes and open questions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent.memory_engine.memories.models import MemoryStatus
from agent.memory_engine.memories.reconciliation import select_reconciliation_candidates
from agent.shared.timeline import date_label, user_zone
from storage import get_user_timezone, list_agent_memories, list_agent_memory_embeddings, list_profile_facts
from storage.open_questions import list_open_questions
from storage.self_notes import list_active_self_notes

MAX_EXISTING_MEMORIES = 8
# Latest user words shown per existing memory, so the model can tell "lives in" from "visiting".
_HISTORY_QUOTES = 2
_HISTORY_QUOTE_CHARS = 120


def memory_history(memory: dict[str, Any], zone: Any) -> dict[str, Any]:
    """How often and when the user said what backs this memory, and their latest words."""
    said = sorted(
        (item for item in memory.get("evidence") or [] if item.get("observed_at")),
        key=lambda item: str(item["observed_at"]),
    )
    days = [
        datetime.fromisoformat(str(item["observed_at"]).replace("Z", "+00:00")).astimezone(zone)
        for item in said
    ]
    return {
        "said_times": len(said),
        "said_on_days": len({day.date() for day in days}),
        "first_said": date_label(days[0]) if days else None,
        "last_said": date_label(days[-1]) if days else None,
        "latest_words": [
            str(item.get("exact_quote") or "")[:_HISTORY_QUOTE_CHARS]
            for item in said[-_HISTORY_QUOTES:]
        ],
    }


def existing_memory_context(
    user_id: str,
    memory_version: int,
    evidence_text: str = "",
    *,
    query_embedding: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if memory_version == 3:
        all_memories = list_agent_memories(user_id)
        stored_embeddings = (
            list_agent_memory_embeddings(
                user_id,
                [str(memory["id"]) for memory in all_memories],
            )
            if query_embedding
            else []
        )
        memories = select_reconciliation_candidates(
            all_memories,
            evidence_text,
            limit=MAX_EXISTING_MEMORIES,
            query_embedding=query_embedding,
            embeddings_by_memory_id={
                str(embedding["memory_id"]): embedding
                for embedding in stored_embeddings
            },
        )
        zone = user_zone(get_user_timezone(user_id))
        return [
            {
                "id": memory["id"],
                "memory_kind": memory["kind"],
                "purposes": memory["purposes"],
                "key": memory["key"],
                "value": memory["value"],
                "sensitivity": memory["sensitivity"],
                "confidence": memory["confidence"],
                "importance": memory["importance"],
                "status": memory["status"],
                "targetable": memory["status"] == MemoryStatus.ACTIVE.value,
                "supersedes_memory_id": memory.get("supersedes_memory_id"),
                "updated_at": memory["updated_at"],
                "statement": memory.get("statement"),
                **({"focus": True} if memory.get("focus") else {}),
                "history": memory_history(memory, zone),
            }
            for memory in memories
        ]

    memories = list_profile_facts(user_id, statuses={"active"})
    memories.sort(key=lambda memory: str(memory.get("updated_at") or ""), reverse=True)
    return [
        {
            "id": memory["id"],
            "data_point_type": memory["fact_type"],
            "category": memory["category"],
            "key": memory["key"],
            "label": memory["label"],
            "value": memory["value"],
            "confidence": memory["confidence"],
        }
        for memory in memories[:MAX_EXISTING_MEMORIES]
    ]


def self_note_context(user_id: str) -> list[dict[str, Any]]:
    return [
        {key: note[key] for key in ("id", "kind", "text", "due_at")}
        for note in list_active_self_notes(user_id, limit=30)
    ]


def open_question_context(user_id: str) -> list[dict[str, Any]]:
    return [
        {key: question[key] for key in ("id", "text", "about_memory_ids", "created_at")}
        for question in list_open_questions(user_id)
    ]


__all__ = ["MAX_EXISTING_MEMORIES", "existing_memory_context", "memory_history", "open_question_context", "self_note_context"]
