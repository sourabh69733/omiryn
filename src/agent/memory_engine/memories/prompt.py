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
  "statement": "one short plain sentence about the user, e.g. Has a job interview at a design studio.",
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
- The companion's own promises, opinions and plans are never memories, even when they are about the
  user ("I'll ask how the interview went"); they belong in self_notes.
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
- occurred_at is the event time, past or scheduled (an interview next Friday, a trip in May), not
  extraction time or send time. Resolve relative dates ("today",
  "yesterday", "last Friday", "next Monday") against the evidence message's sent_at and sent_weekday,
  in user_timezone. Write the resolved day as an ISO-8601 timestamp with that timezone's UTC offset,
  using 12:00 when no time of day is stated. Use null when the day cannot be pinned down, such as
  "recently", "a while ago" or "last year", or when the message has no sent_at.
- Never put relative time words ("next Friday", "yesterday", "last week") in key or value; they go
  stale. Put the time in occurred_at and write the value without it, or with the absolute date.
- statement restates the memory as one short, plain third-person sentence without the user's
  name ("Has a beagle called Bruno.", "Moved from Mumbai to Pune."). Same rules as value: no
  relative time words, no guessing beyond the evidence. At most 240 characters.
- For plans and temporary states, set valid_until only when the evidence gives a clear end
  (for example "this week" ends at the end of that week); otherwise use null.
- Before returning each operation, verify that the cited user evidence directly supports its kind,
  purposes, key, value, sensitivity and time fields. Omit the operation if any field requires guessing.
- Return at most 12 memory operations.
""".replace("{taxonomy_guidance}", V3_MEMORY_TAXONOMY_GUIDANCE).replace(
    "{value_guidance}", V3_MEMORY_VALUE_GUIDANCE
)


__all__ = ["V3_MEMORY_OUTPUT_SHAPE"]
