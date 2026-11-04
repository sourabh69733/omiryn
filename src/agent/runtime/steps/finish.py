"""The last step: strip the model's hidden markers and turn the reply into chat bubbles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.context_engine.policy import split_assistant_reply
from agent.context_engine.policy.replies import strip_quiet_markers, strip_story_end, strip_story_marker, strip_voice_marker
from agent.context_engine.state.turn import assistant_turn_state


@dataclass(frozen=True)
class FinishedReply:
    text: str
    parts: list[str]
    # The model's own marker decides; a keyword in the user's message is only a hint for the note.
    story: bool
    story_ended: bool
    voice: str | None
    # An emoji for the user's message, and whether the model chose to say nothing.
    reaction: str | None = None
    no_reply: bool = False

    @property
    def wordless(self) -> bool:
        return not self.parts


def finish_reply(reply: str, user_text: str) -> FinishedReply:
    reply, story_ended = strip_story_end(reply)
    reply, story_marked = strip_story_marker(reply)
    reply, voice = strip_voice_marker(reply)
    reply, reaction, no_reply = strip_quiet_markers(reply)
    if no_reply or (reaction and not reply):
        return FinishedReply("", [], False, False, voice, reaction, no_reply)
    return FinishedReply(reply, split_assistant_reply(reply, user_text=user_text), story_marked or story_ended, story_ended, voice, reaction)


def assistant_messages(finished: FinishedReply, context_summary: dict[str, Any]) -> list[dict[str, Any]]:
    """One message per bubble; the last one carries the turn state and the story end."""
    messages = []
    last = len(finished.parts) - 1
    for index, part in enumerate(finished.parts):
        message: dict[str, Any] = {"role": "assistant", "content": part}
        if finished.story:
            message["story"] = True  # lets "then?" next turn continue the story
        turn_state = assistant_turn_state(
            part,
            conversation_move=context_summary.get("conversation_move"),
            response_mode=context_summary.get("response_mode"),
        )
        if turn_state and index == last:
            message["turn_state"] = turn_state
        if finished.story and finished.story_ended and index == last:
            message["story_end"] = True
        messages.append(message)
    return messages


__all__ = ["FinishedReply", "assistant_messages", "finish_reply"]
