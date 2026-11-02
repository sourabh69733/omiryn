"""V4.1: when the user gives little, Omi may give little back.

V4 told Omi that "hmm" or "ok" was always its cue to bring something. After "shut up" followed by
"hmm" that pushed it to say the same thing again in new words. V4 stays as it was for rollback.
"""

from __future__ import annotations

from dataclasses import replace

from agent.context_engine.prompt_engine.versions.v4 import V4_GOAL, V4_PROMPT_VERSION

_V4_LITTLE_LINE = """- When they give you little ("nothing", "ok", "hmm"), never mirror their words or praise doing
  nothing. That is your cue to bring something: a thing from might_fit, an opinion, or a playful idea."""

_V4_1_LITTLE_LINE = """- When they give you little ("nothing", "ok", "hmm"), never mirror their words or praise doing
  nothing. If they seem open to more, bring something: a thing from might_fit, an opinion, or a playful
  idea. If they told you to stop, seem done, or you have nothing new, one word or one emoji is the
  whole reply. Never say again what you already said, and do not announce that you will be quiet."""

V4_1_GOAL = V4_GOAL.replace(_V4_LITTLE_LINE, _V4_1_LITTLE_LINE)

V4_1_PROMPT_VERSION = replace(
    V4_PROMPT_VERSION,
    version_id="v4-1",
    name="v4_1_little_for_little",
    reply_goal=V4_1_GOAL,
)
