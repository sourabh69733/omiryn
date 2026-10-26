"""The prompt that rewrites the user card from all memories (see card_rebuild)."""

from agent.cognition.background.memory_run.prompt_v3 import USER_CARD_RULES

CARD_REBUILD_SYSTEM_PROMPT = """You write the user's card from scratch, from what their companion knows
about them. Return one JSON object only: {"user_card": "one fact per line"}.

Input: today (the user's date), memories (each with what is known, its kind, the date it was said or
happened, and for something they are into for a while its focus: current, fading or over), and
current_user_card (only for wording).

- Use only the memories. A line of current_user_card that no memory supports is left out.
- When memories disagree, the newer one wins. Something that ended is written as ended, with when,
  or left out; a fading or over focus is never written as current.
- Always write the whole card here; the rules below about returning null or changing nothing do not
  apply.

""" + USER_CARD_RULES


__all__ = ["CARD_REBUILD_SYSTEM_PROMPT"]
