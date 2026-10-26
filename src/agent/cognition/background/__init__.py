"""Background thinking between replies, grouped by job:

- memory_run: the memory run on a chat (memories, threads, summary, card, vibe).
- uploads: learning from an uploaded chat.
- cards: the daily user card rebuild.
- vibe: vibe line rules, proof checks and backfill.

idle.py decides what runs when the user is idle or comes back; models.py holds shared types.
"""

from agent.cognition.background.memory_run.prompt import BACKGROUND_COGNITION_SYSTEM_PROMPT, background_cognition_prompt

__all__ = [
    "BACKGROUND_COGNITION_SYSTEM_PROMPT",
    "background_cognition_prompt",
]
