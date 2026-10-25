"""Per-turn notes placed after the user's message: the last thing the model reads, which it follows
more reliably than rules in the prompt."""

from __future__ import annotations

from agent.context_engine.conversation_engine.policy.replies import STORY_END_MARKER, STORY_MARKER, STORY_NOTE_PREFIX
from agent.runtime.story_mode import story_autoplay_enabled

_NO_QUESTION_NOTE = "For this reply: react to what the user said or share a thought. Do not ask any question."

_STORY_NOTE = (
    f"{STORY_NOTE_PREFIX} the user asked for a story. Start with {STORY_MARKER} and tell it yourself now in 4-7 short bubbles "
    "separated by <next_message>: a character, a setting and something that happens. Do not ask "
    "the user what should happen."
)
_STORY_CONTINUE_NOTE = (
    f"{STORY_NOTE_PREFIX} the user is following the story you are telling. If they react or ask "
    f"for more, start with {STORY_MARKER}, react in a few words at most, then continue the story from where it stopped in 3-7 "
    "short bubbles separated by <next_message>. Move the plot forward; do not restart or recap. "
    "If they want to stop or have moved on to something else, reply to that instead and add "
    f"{STORY_END_MARKER} at the very end."
)
_STORY_ENDING = " End with an ending or a light 'want more?'."
# With autoplay the story goes on by itself, so a part stops at a pause instead of asking.
_STORY_AUTOPLAY_ENDING = (
    " Stop this part at a natural pause without asking whether to go on; you will continue on "
    f"your own in a moment. When the whole story is finished, add {STORY_END_MARKER} at the very end."
)

_UNANSWERED_NOTE = (
    "The user sent their last {count} messages in a row before you replied. Read them together "
    "and reply once: answer each one that needs an answer, in its own short bubble, and let "
    "greetings or fillers pass without a bubble of their own."
)


def turn_notes(question_limit: int, intent_labels: tuple[str, ...] = (), unanswered_count: int = 1) -> list[dict[str, str]]:
    notes = []
    if unanswered_count > 1:
        notes.append({"role": "system", "content": _UNANSWERED_NOTE.format(count=unanswered_count)})
    ending = _STORY_AUTOPLAY_ENDING if story_autoplay_enabled() else _STORY_ENDING
    if "story_continuation" in intent_labels:
        notes.append({"role": "system", "content": _STORY_CONTINUE_NOTE + ending})
    elif "story_or_long_reply" in intent_labels:
        notes.append({"role": "system", "content": _STORY_NOTE + ending})
    elif question_limit == 0:
        notes.append({"role": "system", "content": _NO_QUESTION_NOTE})
    return notes


__all__ = ["turn_notes"]
