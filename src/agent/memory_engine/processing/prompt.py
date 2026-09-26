"""Defines the model contract for shadow background-memory analysis."""

from __future__ import annotations

import json
from typing import Any

from agent.shared.timeline import parse_time, user_zone

from .models import MemoryBatch, MemoryMessage
from .sessions import batch_sessions


MEMORY_OPERATION_RULES = """Rules:
- New messages are the only source of new observations.
- Context messages and the previous handoff may only resolve meaning and references.
- Only user messages marked evidence_eligible may appear in evidence_message_indexes.
- Do not turn assistant suggestions, descriptions, or guesses into facts about the user.
- Store only explicit, personally true user information; a discussed subject is not an observation.
  Do not store technical explanations, code, examples, definitions, questions, or names merely mentioned.
- profile_fact is a stable user attribute (identity, location, work, or life logistics).
- matching_fact is an explicit partner preference, relationship intent, value, boundary, or lifestyle preference.
- chat_learning is a direct instruction or preference for how Omiryn should converse.
- For each add or supersede, set memory_basis exactly: stable_user_attribute for profile_fact,
  explicit_matching_preference for matching_fact, or direct_chat_preference for chat_learning.
- temporary_context is not supported until it has an expiry lifecycle; return no_change instead.
- Examples: "I work as a designer" may be profile_fact; "smoking is a dealbreaker" may be
  matching_fact; "ask fewer questions" may be chat_learning; a code example or product mention is no_change.
- Use reinforce when new evidence supports an existing memory, supersede for an explicit
  correction, retract when the user explicitly withdraws it, and add only when no supplied
  memory represents the observation.
- Do not create broad labels that omit concrete values stated by the user.
- If there is no useful observation, return decision=no_change and operations=[].
- Return at most 12 operations. Do not invent memory IDs or message indexes.
"""


MEMORY_BACKGROUND_V2_SYSTEM_PROMPT = """You analyze a bounded conversation batch for Omiryn memory.
Return one JSON object and no surrounding prose.

Output shape:
{
  "decision": "propose" | "no_change",
  "operations": [
    {
      "operation": "add" | "reinforce" | "supersede" | "retract",
      "target_memory_id": "required for reinforce/supersede/retract, otherwise null",
      "data_point_type": "profile_fact | matching_fact | chat_learning",
      "memory_basis": "stable_user_attribute | explicit_matching_preference | direct_chat_preference",
      "category": "short semantic category",
      "key": "short_snake_case_key",
      "label": "concrete description of what was learned",
      "value": "useful scalar, array, or object",
      "confidence": 0.0,
      "evidence_message_indexes": [0]
    }
  ],
  "handoff": {
    "summary": "compact context needed by the next batch",
    "active_people": [],
    "active_topics": [],
    "unresolved_references": []
  }
}

""" + MEMORY_OPERATION_RULES


def memory_batch_prompt(
    batch: MemoryBatch,
    existing_memories: list[dict[str, Any]],
    timezone_name: str | None = None,
) -> str:
    """Serialize trusted batch metadata separately from model-generated operations."""
    zone = user_zone(timezone_name)
    labels, sessions = batch_sessions(batch, batch.previous_handoff.session_log)
    payload = {
        "conversation_id": batch.conversation_id,
        "batch_key": batch.batch_key,
        "user_timezone": zone.key,
        "messages": [
            {
                "message_index": message.message_index,
                "role": message.role,
                "content": message.content,
                "scope": message.scope,
                "evidence_eligible": message.evidence_eligible,
                **_sent_fields(message, zone),
                **({"session": labels[message.message_index]} if message.message_index in labels else {}),
                **({"initiated_by_companion": True} if message.initiated_by_companion else {}),
            }
            for message in batch.messages
        ],
        "sessions": [
            {
                "session": session.id,
                "started_at": _local_iso(session.started_at, zone),
                "has_new_messages": session.has_new_messages,
            }
            for session in sessions
        ],
        "previous_handoff": {
            "summary": batch.previous_handoff.summary,
            "active_people": list(batch.previous_handoff.active_people),
            "active_topics": list(batch.previous_handoff.active_topics),
            "unresolved_references": list(batch.previous_handoff.unresolved_references),
            "conversation_summary": batch.previous_handoff.conversation_summary,
            "session_log": [
                {
                    "session": _label_for(entry.started_at, sessions),
                    "started_at": _local_iso(entry.started_at, zone),
                    "gist": entry.gist,
                    "unfinished": entry.unfinished or None,
                }
                for entry in batch.previous_handoff.session_log[-3:]
            ],
        },
        "existing_memories": existing_memories,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _local_iso(value: str, zone: Any) -> str:
    parsed = parse_time(value)
    return parsed.astimezone(zone).isoformat(timespec="minutes") if parsed else value


def _label_for(started_at: str, sessions: list[Any]) -> str:
    """The batch label when this logged session continues in the batch, else 'earlier'."""
    return next((s.id for s in sessions if s.started_at == started_at), "earlier")


def _sent_fields(message: MemoryMessage, zone: Any) -> dict[str, str]:
    """Local send time, so relative dates like 'yesterday' can be resolved."""
    sent = parse_time(message.sent_at)
    if sent is None:
        return {}
    local = sent.astimezone(zone)
    return {
        "sent_at": local.isoformat(timespec="minutes"),
        "sent_weekday": local.strftime("%A"),
    }
