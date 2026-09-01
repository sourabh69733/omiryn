"""Defines the combined background-cognition prompt for v3 durable memories."""

from agent.memory_engine.memories.prompt import V3_MEMORY_OUTPUT_SHAPE


BACKGROUND_COGNITION_V3_SYSTEM_PROMPT = """You analyze one bounded Omiryn conversation batch.
Return one JSON object and no surrounding prose.

Output shape:
{
  "decision": "propose | no_change",
  "operations": ["v3 memory operations described below"],
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

""" + V3_MEMORY_OUTPUT_SHAPE


__all__ = ["BACKGROUND_COGNITION_V3_SYSTEM_PROMPT"]
