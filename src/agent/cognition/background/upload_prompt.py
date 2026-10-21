"""The wrap-up after an upload's parts were read at the same time: one short call merges them.

Its answer is mostly IDs, so it stays fast: the model groups memories that say the same thing and
picks vibe lines; code copies the chosen text and joins the proof.
"""

from agent.cognition.background.prompt_v3 import USER_CARD_RULES
from agent.memory_engine.memories.vibe import VIBE_LINE_RULES

UPLOAD_WRAP_UP_SYSTEM_PROMPT = """You finish learning from a chat the user uploaded. Its parts were read
separately, so the same thing may have been learned more than once. Return one JSON object only.

Input:
- candidates: memories learned from the parts, each with an id.
- current_user_card: the user's card before this upload.
- vibe_areas: what each friend-vibe area means; current_vibe: lines written so far.
- vibe_candidates: per area, lines the parts wrote, each with an id.

Output:
{
  "same": [["<candidate id>", "<candidate id>"]],
  "user_card": "the updated card, one fact per line; null only to keep a current_user_card unchanged",
  "vibe": {"<area id>": {"line": "one line for the area", "from": ["<vibe candidate id>"]}}
}

same: groups of candidate ids that say the same thing about the user (one fact, one event, one
person). Leave a candidate out when nothing else matches it. Never group different facts.

user_card: when current_user_card is empty, always write it from the candidates.

vibe: at most one line per area. "from" lists what shows it: vibe candidate ids and memory candidate
ids. Write the line only from what those say, joining them when they agree; leave an area out when
nothing shows it.
""" + VIBE_LINE_RULES + """

User card rules (current_user_card is the starting point; candidates are the new messages):
""" + USER_CARD_RULES


__all__ = ["UPLOAD_WRAP_UP_SYSTEM_PROMPT"]
