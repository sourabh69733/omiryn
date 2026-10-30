"""Replies on messaging apps (Telegram, WhatsApp): quick messages are grouped and answered together.

Each app passes a `ChannelSender` that knows how to send text and show typing there.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from fastapi import BackgroundTasks, HTTPException

from agent.shared.clock import utc_now
from security.auth import CurrentUser
from storage import burst_state, finish_burst, join_burst, release_burst

from ..chat_service import (
    commit_reply,
    draft_reply_to_unanswered,
    mark_unanswered_failed,
    save_unanswered_message,
)

logger = logging.getLogger(__name__)

# A short pause between bubbles, so they arrive like someone typing them.
BUBBLE_PAUSE_SECONDS = 0.8
# People often send a thought in several quick messages. Omi waits for this much quiet before
# replying, but never longer than the max, and then answers them together.
QUIET_SECONDS = 1.5
MAX_WAIT_SECONDS = 6.0
# Times a draft is thrown away because more messages came in before any bubble was sent.
MAX_RESTARTS = 2
# How long one instance may hold a chat's burst; a crashed replier's lease runs out and the next
# message's instance takes over.
BURST_LEASE_SECONDS = 600.0
# While waiting for quiet, the burst row is re-read this often for messages that reached another instance.
_QUIET_POLL_SECONDS = 0.25

REPLY_FAILED = "Couldn't reply right now. Send your message again in a bit."


@dataclass(frozen=True)
class ChannelSender:
    channel: str
    send_text: Callable[[str, str], Awaitable[Any]]
    send_typing: Callable[[str], Awaitable[Any]]
    # How long the app shows "typing…" after one call; renewed before it fades.
    typing_refresh_seconds: float


@dataclass
class _Burst:
    """Messages one chat sent since Omi last replied, as counted in the database (`channel_bursts`),
    so messages that reach another server instance join the same burst. Only the holder of the
    replier lease answers."""

    channel: str
    chat_id: str
    conversation_id: str
    token: str

    def state(self) -> dict[str, Any] | None:
        return burst_state(self.channel, self.chat_id)


async def handle_channel_message(
    sender: ChannelSender,
    chat_id: str,
    user: CurrentUser,
    text: str,
    background_tasks: BackgroundTasks,
) -> None:
    """Save the message now; the first message of a burst then replies to the whole burst.

    Returns at once for a message that joins a burst already being answered.
    """
    try:
        conversation = await save_unanswered_message(user, text, sender.channel)
    except HTTPException as error:
        await sender.send_text(chat_id, failure_text(error))
        return
    joined = join_burst(sender.channel, chat_id, conversation.id, now=utc_now(), lease_seconds=BURST_LEASE_SECONDS)
    if not joined["token"]:
        return
    burst = _Burst(sender.channel, chat_id, conversation.id, joined["token"])
    try:
        await _reply_to_burst(sender, chat_id, user, burst, background_tasks)
    finally:
        release_burst(burst.channel, burst.chat_id, burst.token)


def failure_text(error: HTTPException) -> str:
    if error.status_code == 429 and isinstance(error.detail, str):
        return error.detail
    return REPLY_FAILED


async def _reply_to_burst(
    sender: ChannelSender,
    chat_id: str,
    user: CurrentUser,
    burst: _Burst,
    background_tasks: BackgroundTasks,
) -> None:
    restarts = 0
    while True:
        seen = await _wait_for_quiet(burst)
        if seen is None:
            return  # the burst was closed under us (lease taken over)
        await sender.send_typing(chat_id)
        typing = asyncio.create_task(_keep_typing(sender, chat_id))
        try:
            draft = await draft_reply_to_unanswered(user, burst.conversation_id)
            state = burst.state()
            if state and state["arrivals"] > seen and restarts < MAX_RESTARTS:
                # More came in while Omi wrote: start over so the reply covers those too.
                restarts += 1
                continue
            replies = await commit_reply(user, draft, background_tasks) if draft else []
        except Exception as error:
            if not isinstance(error, HTTPException):
                logger.exception("channel.reply.failed channel=%s", sender.channel)
            _mark_failed(user, burst.conversation_id)
            await sender.send_text(chat_id, REPLY_FAILED)
            return
        finally:
            typing.cancel()
            with suppress(asyncio.CancelledError):
                await typing
        restarts = 0
        await _send_bubbles(sender, chat_id, replies)
        # Closes the burst only if nothing arrived since `seen`; otherwise go round again.
        if finish_burst(burst.channel, burst.chat_id, burst.token, answered=seen):
            return


async def _wait_for_quiet(burst: _Burst) -> int | None:
    """Wait for the chat to go quiet; returns how many messages the burst then holds."""
    deadline = utc_now().timestamp() + MAX_WAIT_SECONDS
    while True:
        state = burst.state()
        if state is None:
            return None
        wait = min(state["last_at"].timestamp() + QUIET_SECONDS, deadline) - utc_now().timestamp()
        if wait <= 0:
            return state["arrivals"]
        await asyncio.sleep(min(wait, _QUIET_POLL_SECONDS))


async def _send_bubbles(sender: ChannelSender, chat_id: str, replies: list[dict[str, Any]]) -> None:
    bubbles = [
        str(message.get("content") or "").strip()
        for message in replies
        if message.get("role") == "assistant"
    ]
    for index, bubble in enumerate(bubble for bubble in bubbles if bubble):
        if index:
            await sender.send_typing(chat_id)
            await asyncio.sleep(BUBBLE_PAUSE_SECONDS)
        await sender.send_text(chat_id, bubble)


async def _keep_typing(sender: ChannelSender, chat_id: str) -> None:
    while True:
        await asyncio.sleep(sender.typing_refresh_seconds)
        await sender.send_typing(chat_id)


def _mark_failed(user: CurrentUser, conversation_id: str) -> None:
    try:
        mark_unanswered_failed(user, conversation_id)
    except Exception:
        logger.exception("channel.mark_failed.failed")
