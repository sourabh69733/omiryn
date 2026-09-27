"""Runs a story_part job: the next part of a story the user is listening to."""

from __future__ import annotations

import logging
from typing import Any

from agent.context_engine.conversation_engine.policy import split_assistant_reply
from agent.context_engine.conversation_engine.policy.replies import (
    STORY_END_MARKER,
    strip_story_end,
    strip_story_marker,
)
from agent.runtime.story_mode import (
    STORY_CHECK_IN_EVERY,
    auto_parts_since_user,
    schedule_story_part,
    story_autoplay_enabled,
    story_part_block_reason,
)
from agent.shared.clock import utc_now
from realtime import realtime_hub
from storage import get_conversation

from .service import deliver_messages, generate_initiative_text

logger = logging.getLogger(__name__)

_STORY_PART_INSTRUCTIONS = """

STORY MODE
You are telling the user a story and they are listening without replying. Continue it from
exactly where it stopped, in 2-4 short bubbles separated by <next_message>. Move the plot forward;
do not recap, restart or ask the user what should happen.
{ending}
When the whole story is finished, close it properly and add {marker} at the very end.
"""
_PAUSE = "Stop this part at a natural pause without asking anything; you will go on in a moment."
_CHECK_IN = "End this part with one light check-in, such as asking if they are still with you."
_CUE = "(The user is still listening. Continue the story now.)"


async def run_story_part_job(job: dict[str, Any]) -> bool:
    """Send the next part if the story is still running and the user is watching."""
    user_id, conversation_id = str(job["user_id"]), str(job["conversation_id"])
    if not story_autoplay_enabled():
        return False
    conversation = get_conversation(conversation_id, user_id)
    if not conversation or conversation.get("status") != "active":
        return False
    messages = conversation["messages"]
    if story_part_block_reason(messages):
        return False
    if (user_id, conversation_id) not in await realtime_hub.live_conversations():
        return False  # paused: "continue" from the user picks it up again
    part = auto_parts_since_user(messages) + 1
    check_in = part >= STORY_CHECK_IN_EVERY
    text = await generate_initiative_text(
        conversation,
        user_id,
        user_text="continue the story",
        instructions=_STORY_PART_INSTRUCTIONS.format(
            ending=_CHECK_IN if check_in else _PAUSE, marker=STORY_END_MARKER
        ),
        cue=_CUE,
        max_tokens=600,
    )
    text, ended = strip_story_end(text or "")
    text, _ = strip_story_marker(text)
    bubbles = [bubble for bubble in split_assistant_reply(text, user_text="") if bubble.strip()]
    if not bubbles:
        return False
    now = utc_now().isoformat()
    new_messages = [
        {"role": "assistant", "content": bubble, "story": True, "story_auto": part, "created_at": now}
        for bubble in bubbles
    ]
    if ended:
        new_messages[-1]["story_end"] = True
    delivered = await deliver_messages(
        user_id, conversation_id, expected_count=len(messages), new_messages=new_messages
    )
    if delivered and story_part_block_reason([*messages, *new_messages]) is None:
        schedule_story_part(user_id, conversation_id)
    return delivered


__all__ = ["run_story_part_job"]
