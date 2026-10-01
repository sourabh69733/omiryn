"""Builds the provider-neutral input for combined background cognition."""

from __future__ import annotations

import json
from typing import Any

from agent.memory_engine.memories.vibe import VIBE_AREAS
from agent.memory_engine.processing.models import MemoryBatch
from agent.memory_engine.processing.prompt import (
    MEMORY_OPERATION_RULES,
    memory_batch_prompt,
)


BACKGROUND_COGNITION_SYSTEM_PROMPT = """You analyze one bounded Omiryn conversation batch.
Return one JSON object and no surrounding prose.

Output shape:
{
  "decision": "propose" | "no_change",
  "operations": [
    {
      "operation": "add" | "reinforce" | "supersede" | "retract",
      "target_memory_id": "supplied ID or null",
      "data_point_type": "profile_fact | matching_fact | chat_learning",
      "memory_basis": "stable_user_attribute | explicit_matching_preference | direct_chat_preference",
      "category": "short semantic category",
      "key": "short_snake_case_key",
      "label": "concrete description",
      "value": "useful scalar, array, or object",
      "confidence": 0.0,
      "evidence_message_indexes": [0]
    }
  ],
  "thread_operation": {
    "operation": "none | create | continue | switch | pause | complete | block",
    "thread_id": "supplied ID or null",
    "title": "required only for create or null",
    "summary": "updated compact summary or null",
    "origin": "user_started | agent_started | null",
    "matching_dimension": "short dimension or null",
    "depth": "mentioned | explored | meaningful | null",
    "user_interest": "unknown | low | medium | high | null",
    "salience": 0.0,
    "next_angle": "possible continuation or null",
    "closure_reason": "reason or null"
  },
  "handoff": {
    "summary": "context needed by the next batch",
    "active_people": [],
    "active_topics": [],
    "unresolved_references": []
  }
}

Thread rules:
- Return exactly one thread_operation.
- Use {"operation":"none"} for no meaningful thread change.
- Create requires title, summary, and origin and must not contain an ID.
- Other operations require one ID supplied in existing_threads.
- Never change an existing origin or reopen completed or blocked threads.
- Choose the clearest primary transition; keep other unresolved subjects in handoff.
- decision=no_change requires operations=[] and thread_operation=none.
- Any memory or thread proposal requires decision=propose.

""" + MEMORY_OPERATION_RULES


def background_cognition_prompt(
    batch: MemoryBatch,
    existing_memories: list[dict[str, Any]],
    thread_candidates: list[dict[str, object]],
    timezone_name: str | None = None,
    user_card: str | None = None,
    self_notes: list[dict[str, Any]] | None = None,
    vibe: dict[str, str] | None = None,
) -> str:
    """Serialize one shared batch for memory and thread analysis."""
    payload = json.loads(memory_batch_prompt(batch, existing_memories, timezone_name))
    payload["existing_threads"] = thread_candidates
    if user_card is not None:
        payload["current_user_card"] = user_card
    if self_notes is not None:
        payload["existing_self_notes"] = self_notes
    if vibe is not None:
        payload["vibe_areas"] = [{"id": area_id, "meaning": goal} for area_id, _, goal in VIBE_AREAS]
        payload["current_vibe"] = vibe
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


__all__ = ["BACKGROUND_COGNITION_SYSTEM_PROMPT", "background_cognition_prompt"]
