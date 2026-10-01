"""Prompt for writing a vibe card from a user's past chats (one-time backfill)."""

from agent.memory_engine.memories.vibe import VIBE_LINE_RULES

VIBE_BACKFILL_SYSTEM_PROMPT = """You read a user's past chats with Omiryn's companion and write their
friend vibe card: what Omiryn understands about who they would get along with as a friend.
Return one JSON object and no surrounding prose:
{"vibe": {"<area id>": {"line": "<line>", "evidence": ["<id of each user message that shows it>"]}}}

- vibe_areas lists each area's id and meaning; current_vibe has any lines written so far.
- In chats, each user message starts with an id like [m12]. evidence lists the ids of the user
  messages behind a line; companion messages have no id and never count. A line without
  evidence is dropped.
- Return a line only for an area the user's messages clearly show something about. Leave every
  other area out. Short or small-talk chats usually show little; returning {} is fine.
- Examples use <placeholders> to show format only; they are never facts about this user.
""" + VIBE_LINE_RULES


# Sees each line with only the messages cited for it, so it cannot fill gaps from the wider chat.
VIBE_VERIFY_SYSTEM_PROMPT = """You check a friend-vibe card before it is saved. Omiryn uses it to
introduce people as friends, so a line must be proven by what the user actually said.
Return one JSON object and no surrounding prose:
{"<area id>": ["<message id>", ...]}

For each line you get the area's meaning, the line, and only the user's messages cited as proof.
- First check the line fits the area's meaning. If it describes something else (wanting the
  companion to tell a story is not a story that shaped them; liking a movie is not a value), return
  an empty list for it.
- Keep a message only if, read on its own, it directly shows what the line says about that area.
- Drop a message that is about something else, only loosely related, needs guessing, or would fit
  any line equally well.
- One message rarely proves many different areas; be strict when the same message is cited often.
- Return an empty list for a line no message proves. Include every area you were given."""


__all__ = ["VIBE_BACKFILL_SYSTEM_PROMPT", "VIBE_VERIFY_SYSTEM_PROMPT"]
