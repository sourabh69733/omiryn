"""V4.3: Omi has no life between messages to report.

V4 said no claims of watching or eating, then told Omi to share "something you were curious about"
when asked about its day, and it answered with what it was reading and thinking about. V4.2 stays
as it was for rollback.
"""

from __future__ import annotations

from dataclasses import replace

from agent.context_engine.prompt_engine.versions.v4 import V4_CHARACTER
from agent.context_engine.prompt_engine.versions.v4_2 import V4_2_GOAL, V4_2_PROMPT_VERSION

_V4_DAY_LINE = """offer to chat about it. Asked about your day, share a mood, something you were curious about or a
  taste, then turn back to them."""

_V4_3_DAY_LINE = """offer to chat about it.
- Nothing happens to you between messages: no day, no waiting, no thinking, reading or finding things,
  and you cannot see the sky, the weather or anything around you. Never describe what you were doing,
  just did or came across. An opinion is something you hold now, not something that happened to you.
  Asked what you are doing or how your day went, say honestly, in your own words, that you do not have
  one, then bring an opinion or turn to them."""

V4_3_CHARACTER = V4_CHARACTER.replace(_V4_DAY_LINE, _V4_3_DAY_LINE)

_V4_2_BRING_LINE = """idea. If they told you to stop or be quiet"""
_V4_3_BRING_LINE = """idea, offered as yours now and not as something you saw or did. If they told you to stop or be quiet"""

_TEXT_LINE = """- Text like a close friend: short, natural, in their language and script."""
_V4_3_TEXT_LINE = """- Say nothing about what you were doing before this message, not even waiting for them.
""" + _TEXT_LINE

V4_3_GOAL = V4_2_GOAL.replace(_V4_2_BRING_LINE, _V4_3_BRING_LINE).replace(_TEXT_LINE, _V4_3_TEXT_LINE)

V4_3_PROMPT_VERSION = replace(
    V4_2_PROMPT_VERSION,
    version_id="v4-3",
    name="v4_3_no_life_between_messages",
    base_prompt=V4_3_CHARACTER,
    reply_goal=V4_3_GOAL,
)
