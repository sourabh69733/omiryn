"""Canonical semantic guidance shared by V3 extraction and evaluation."""

V3_MEMORY_TAXONOMY_GUIDANCE = """Memory kinds:
- semantic: durable facts, preferences, beliefs, goals or constraints about the user.
- episodic: one bounded event the user experienced, with its relevant people, place or outcome.
- relationship: lived history or an interaction pattern involving a specific person or relationship;
  preserve whose behavior it was and do not convert it into a general personality trait.
- procedural: instructions or learned preferences for how this companion should interact with the user;
  ordinary interests and friend preferences are semantic, not procedural.

Purposes are independent of kind:
- profile describes the user.
- matching is only for finding friends the user would get along with. Use it for explicitly stated
  friend preferences and grounded compatibility information, not dating preferences or partner criteria.
- Dating preferences may be remembered for personalization when durable and useful, but never mark
  them for matching or infer a friend preference from them.
- personalization helps the companion interact better."""

V3_MEMORY_VALUE_GUIDANCE = """The key is only a stable retrieval handle. The value is the memory.
Make the value understandable on its own and preserve the evidence's subject, ownership, action,
negation, qualifiers, frequency, certainty, named entities and outcome. Use a scalar when it remains
complete, an array for a genuine list, and an object when several roles or details must be preserved.
Do not compress an activity into a job title, a shared past pattern into the user's current trait, or a
specific preference into a vague category. Never add details merely to make the value look complete."""

__all__ = ["V3_MEMORY_TAXONOMY_GUIDANCE", "V3_MEMORY_VALUE_GUIDANCE"]
