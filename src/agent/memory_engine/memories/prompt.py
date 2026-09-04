"""Defines the concise v3 memory lane contract for background cognition."""

V3_MEMORY_OUTPUT_SHAPE = """V3 memory operations:

add creates a new memory:
{
  "operation": "add",
  "memory_kind": "semantic | episodic | relationship | procedural",
  "purposes": ["profile | matching | personalization"],
  "key": "short stable semantic key",
  "value": "specific scalar, array, or object",
  "sensitivity": "standard | sensitive | highly_sensitive",
  "confidence": 0.0,
  "importance": 0.0,
  "occurred_at": "timezone-aware ISO-8601 timestamp or null",
  "valid_from": "timezone-aware ISO-8601 timestamp or null",
  "valid_until": "timezone-aware ISO-8601 timestamp or null",
  "evidence_message_indexes": [0]
}

reinforce adds supporting evidence without changing meaning:
{
  "operation": "reinforce",
  "target_memory_id": "supplied active memory ID",
  "confidence": 0.0,
  "importance": 0.0,
  "evidence_message_indexes": [0]
}

supersede corrects an active memory. It has target_memory_id plus every add field.
retract invalidates an active memory:
{
  "operation": "retract",
  "target_memory_id": "supplied active memory ID",
  "evidence_message_indexes": [0]
}

V3 memory rules:
- New evidence-eligible user messages are the only source of durable memories.
- Context messages, existing memories and handoff only resolve meaning and prevent duplicates.
- Store personally true, useful information—not discussed subjects, examples, code or assistant claims.
- semantic stores stable knowledge, including explicit partner preferences; episodic stores a
  specific lived event; relationship stores the user's lived history or interaction pattern with a
  specific person or relationship; procedural stores an explicit or repeatedly supported preference
  for how the companion should interact.
- purposes describe utility independently of memory_kind. A relationship memory is not automatically
  a matching preference.
- Use profile for facts describing the user, matching for explicit compatibility-relevant information,
  and personalization for information that helps the companion interact better.
- Be concrete: preserve named people, places, preferences and outcomes when explicitly stated.
- Preserve the scope and tense of the evidence. Do not turn a project into a profession, a past shared
  behavior into a current personality trait, or a desired partner quality into the user's own trait.
- Return no memory for uncertainty, incidental mentions, generic knowledge, or unsupported inference.
- When an active memory already expresses the same meaning, reinforce it; never add a duplicate.
- When new evidence corrects an active memory, supersede it with a complete corrected replacement.
- Retract only when the user invalidates a memory without supplying a corrected replacement.
- Never target an ID outside existing_memories and never target one memory twice in a batch.
- Relationship history and intimate interpersonal details are at least sensitive. Medical, biometric,
  sexual, financial and similarly high-risk private facts are highly_sensitive.
- occurred_at is the event time, not extraction time. Use null for relative or ambiguous dates; emit a
  timestamp only when the evidence supports an unambiguous timezone-aware ISO-8601 value.
- Before returning each operation, verify that the cited user evidence directly supports its kind,
  purposes, key, value, sensitivity and time fields. Omit the operation if any field requires guessing.
- Return at most 12 memory operations.
"""


__all__ = ["V3_MEMORY_OUTPUT_SHAPE"]
