"""Prompt for writing a vibe card from a user's past chats (one-time backfill)."""

from agent.memory_engine.memories.vibe import VIBE_LINE_RULES

VIBE_BACKFILL_SYSTEM_PROMPT = """You read a user's past chats with Omiryn's companion and write their
friend vibe card: what Omiryn understands about who they would get along with as a friend.
Return one JSON object and no surrounding prose:
{"vibe": {"<area id>": "<line>"}}

- vibe_areas lists each area's id and meaning; current_vibe has any lines written so far.
- Return a line only for an area the user's messages clearly show something about. Leave every
  other area out. Short or small-talk chats usually show little; returning {} is fine.
- Examples use <placeholders> to show format only; they are never facts about this user.
""" + VIBE_LINE_RULES


__all__ = ["VIBE_BACKFILL_SYSTEM_PROMPT"]
