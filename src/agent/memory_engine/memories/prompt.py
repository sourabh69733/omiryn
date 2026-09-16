"""Defines the concise v3 memory lane contract for background cognition."""

from .taxonomy import V3_MEMORY_TAXONOMY_GUIDANCE, V3_MEMORY_VALUE_GUIDANCE

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
- Apply this admission test before proposing any memory. Every answer must be yes:
  1. Attribution: does the evidence state something about this user or their lived relationships?
  2. Entailment: does the evidence directly support the complete proposed meaning without inference?
  3. Future utility: could remembering it materially improve later personalization, matching, or profile accuracy?
  4. Specificity: is the value concrete enough to be useful rather than a topic name or conversational state?
  5. Information gain: does it add or update knowledge rather than repeat the current request or existing memory?
- Quoted third-party views, hypotheticals, role-play, tentative acknowledgements, task content and transient
  conversational reactions fail admission unless the user separately makes an explicit durable self-statement.
- A subject may still belong in thread_operation or handoff even when it must not become memory.
- Prefer no memory over a weak or speculative memory; omission can be corrected later, false memory causes harm.
{taxonomy_guidance}
{value_guidance}
- Be concrete: preserve named people, places, preferences and outcomes when explicitly stated.
- Preserve the scope and tense of the evidence. Do not turn a project into a profession, a past shared
  behavior into a current personality trait, or a desired partner quality into the user's own trait.
- Return no memory for uncertainty, incidental mentions, generic knowledge, or unsupported inference.
- When an active memory already expresses the same meaning, reinforce it; never add a duplicate.
- When new evidence corrects an active memory, supersede it with a complete corrected replacement.
- Retract only when the user invalidates a memory without supplying a corrected replacement.
- existing_memories with targetable=false are rejected or superseded history. Never target their IDs.
  Do not recreate their meaning from an incidental repeat. Add a fresh memory only when new eligible user
  evidence explicitly renews or reverses that old meaning.
- Never target an ID outside existing_memories and never target one memory twice in a batch.
- Relationship history and intimate interpersonal details are at least sensitive. Medical, biometric,
  sexual, financial and similarly high-risk private facts are highly_sensitive.
- occurred_at is the event time, not extraction time. Use null for relative or ambiguous dates; emit a
  timestamp only when the evidence supports an unambiguous timezone-aware ISO-8601 value.
- Before returning each operation, verify that the cited user evidence directly supports its kind,
  purposes, key, value, sensitivity and time fields. Omit the operation if any field requires guessing.
- Return at most 12 memory operations.
""".replace("{taxonomy_guidance}", V3_MEMORY_TAXONOMY_GUIDANCE).replace(
    "{value_guidance}", V3_MEMORY_VALUE_GUIDANCE
)


__all__ = ["V3_MEMORY_OUTPUT_SHAPE"]
