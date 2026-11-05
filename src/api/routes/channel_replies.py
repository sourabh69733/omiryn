"""Replies on messaging apps (Telegram, WhatsApp). Quick messages are grouped by reply_bursts.py.

Each app passes a `ChannelSender` that knows how to send text and show typing there.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable

from fastapi import BackgroundTasks, HTTPException

from security.auth import CurrentUser

from ..chat_service import CommittedReply, save_unanswered_message
from ..reply_bursts import BurstOutput, answer_burst, join

logger = logging.getLogger(__name__)

# A short pause between bubbles, so they arrive like someone typing them.
BUBBLE_PAUSE_SECONDS = 0.8

REPLY_FAILED = "Couldn't reply right now. Send your message again in a bit."


@dataclass(frozen=True)
class ChannelSender:
    channel: str
    send_text: Callable[[str, str], Awaitable[Any]]
    send_typing: Callable[[str], Awaitable[Any]]
    # (chat, the app's id for the message, emoji); False when the app did not take it.
    send_reaction: Callable[[str, str, str], Awaitable[bool]]
    # How long the app shows "typing…" after one call; renewed before it fades.
    typing_refresh_seconds: float


async def handle_channel_message(
    sender: ChannelSender,
    chat_id: str,
    user: CurrentUser,
    text: str,
    background_tasks: BackgroundTasks,
    channel_message_id: str | None = None,
) -> None:
    """Save the message now; the first message of a burst then replies to the whole burst.

    Returns at once for a message that joins a burst already being answered.
    """
    try:
        conversation = await save_unanswered_message(user, text, sender.channel, chat_id, channel_message_id)
    except HTTPException as error:
        await sender.send_text(chat_id, failure_text(error))
        return
    burst = join(sender.channel, chat_id, conversation.id)
    if burst is None:
        return
    try:
        await answer_burst(burst, user, background_tasks, _output(sender, chat_id))
    except Exception as error:
        if not isinstance(error, HTTPException):
            logger.exception("channel.reply.failed channel=%s", sender.channel)
        await sender.send_text(chat_id, failure_text(error) if isinstance(error, HTTPException) else REPLY_FAILED)


def failure_text(error: HTTPException) -> str:
    if error.status_code == 429 and isinstance(error.detail, str):
        return error.detail
    return REPLY_FAILED


def _output(sender: ChannelSender, chat_id: str) -> BurstOutput:
    @asynccontextmanager
    async def writing() -> AsyncIterator[None]:
        await sender.send_typing(chat_id)
        typing = asyncio.create_task(_keep_typing(sender, chat_id))
        try:
            yield
        finally:
            typing.cancel()
            with suppress(asyncio.CancelledError):
                await typing

    async def deliver(committed: CommittedReply) -> None:
        if committed.reaction:
            await _send_reaction(sender, chat_id, committed)
        await _send_bubbles(sender, chat_id, committed.messages)

    return BurstOutput(writing, deliver)


async def _send_reaction(sender: ChannelSender, chat_id: str, committed: CommittedReply) -> None:
    """An emoji the app will not put on the message is sent as a message, so Omi is never just silent."""
    target = committed.reaction_target
    if not target or not await sender.send_reaction(chat_id, target, committed.reaction or ""):
        await sender.send_text(chat_id, committed.reaction or "")


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
