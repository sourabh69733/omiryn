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

from security.auth import CurrentUser

from .conversations import (
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
    """Messages one chat sent since Omi last replied. Only the first one's handler replies."""

    conversation_id: str
    arrivals: int = 0
    last_at: float = 0.0
    replying: bool = False


_bursts: dict[tuple[str, str], _Burst] = {}


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
    key = (sender.channel, chat_id)
    burst = _bursts.setdefault(key, _Burst(conversation_id=conversation.id))
    burst.arrivals += 1
    burst.last_at = asyncio.get_running_loop().time()
    if burst.replying:
        return
    burst.replying = True
    try:
        await _reply_to_burst(sender, chat_id, user, burst, background_tasks)
    finally:
        _bursts.pop(key, None)


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
    answered = 0
    restarts = 0
    while burst.arrivals > answered:
        await _wait_for_quiet(burst)
        seen = burst.arrivals
        await sender.send_typing(chat_id)
        typing = asyncio.create_task(_keep_typing(sender, chat_id))
        try:
            draft = await draft_reply_to_unanswered(user, burst.conversation_id)
            if burst.arrivals > seen and restarts < MAX_RESTARTS:
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
        answered = seen
        restarts = 0
        await _send_bubbles(sender, chat_id, replies)


async def _wait_for_quiet(burst: _Burst) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + MAX_WAIT_SECONDS
    while True:
        wait = min(burst.last_at + QUIET_SECONDS, deadline) - loop.time()
        if wait <= 0:
            return
        await asyncio.sleep(wait)


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
