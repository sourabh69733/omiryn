"""Defines the model contract for shadow background-memory analysis."""

from __future__ import annotations

import json
from typing import Any

from .models import MemoryBatch


MEMORY_BACKGROUND_V2_SYSTEM_PROMPT = """You analyze a bounded conversation batch for Omiryn memory.
Return one JSON object and no surrounding prose.

Output shape:
{
  "decision": "propose" | "no_change",
  "operations": [
    {
      "operation": "add" | "reinforce" | "supersede" | "retract",
      "target_memory_id": "required for reinforce/supersede/retract, otherwise null",
      "data_point_type": "profile_fact | matching_fact | chat_learning | temporary_context",
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

Rules:
- New messages are the only source of new observations.
- Context messages and the previous handoff may only resolve meaning and references.
- Only user messages marked evidence_eligible may appear in evidence_message_indexes.
- Do not turn assistant suggestions, descriptions, or guesses into facts about the user.
- profile_fact is limited to stable identity or logistics. Preferences, tastes, values,
  lifestyle, boundaries, relationship intent, and partner preferences are matching_fact.
- chat_learning is only about how conversation with this user should work.
- temporary_context is short-lived current context, not a durable trait.
- Use reinforce when new evidence supports an existing memory, supersede for an explicit
  correction, retract when the user explicitly withdraws it, and add only when no supplied
  memory represents the observation.
- Do not create broad labels that omit concrete values stated by the user.
- If there is no useful observation, return decision=no_change and operations=[].
- Return at most 12 operations. Do not invent memory IDs or message indexes.
"""


def memory_batch_prompt(
    batch: MemoryBatch,
    existing_memories: list[dict[str, Any]],
) -> str:
    """Serialize trusted batch metadata separately from model-generated operations."""
    payload = {
        "conversation_id": batch.conversation_id,
        "batch_key": batch.batch_key,
        "messages": [
            {
                "message_index": message.message_index,
                "role": message.role,
                "content": message.content,
                "scope": message.scope,
                "evidence_eligible": message.evidence_eligible,
            }
            for message in batch.messages
        ],
        "previous_handoff": {
            "summary": batch.previous_handoff.summary,
            "active_people": list(batch.previous_handoff.active_people),
            "active_topics": list(batch.previous_handoff.active_topics),
            "unresolved_references": list(batch.previous_handoff.unresolved_references),
        },
        "existing_memories": existing_memories,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
