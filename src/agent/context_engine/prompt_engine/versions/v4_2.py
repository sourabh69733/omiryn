"""V4.2: Omi can answer without words, with one emoji on the user's message or nothing at all.

V4.1 let a whole reply be one word or one emoji, but every reply was still a bubble, and after "go
silent now" then "hmmm" it wrote a new line. V4.1 stays as it was for rollback.
"""

from __future__ import annotations

from dataclasses import replace

from agent.context_engine.prompt_engine.versions.v4_1 import _V4_1_LITTLE_LINE, V4_1_GOAL, V4_1_PROMPT_VERSION

_V4_2_LITTLE_LINE = """- When they give you little ("nothing", "ok", "hmm"), never mirror their words or praise doing
  nothing. If they seem open to more, bring something: a thing from might_fit, an opinion, or a playful
  idea. If they told you to stop or be quiet, seem done, or you have nothing new, answer without words.
  Never say again what you already said, and do not announce that you will be quiet.
- You can answer without words. <react:👍> as your whole reply puts one emoji of your choice on their
  message, the way a friend reacts in a chat app, and sends no bubble. <no_reply> as your whole reply
  sends nothing at all. A reaction suits a message that only needs to be seen. Saying nothing suits
  someone who told you to go quiet, until they write something that wants an answer. Most messages
  still deserve words."""

V4_2_GOAL = V4_1_GOAL.replace(_V4_1_LITTLE_LINE, _V4_2_LITTLE_LINE)

V4_2_PROMPT_VERSION = replace(
    V4_1_PROMPT_VERSION,
    version_id="v4-2",
    name="v4_2_answer_without_words",
    reply_goal=V4_2_GOAL,
)
