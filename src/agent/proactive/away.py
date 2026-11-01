"""Reaches users who are away from the app, in their Telegram or WhatsApp chat with Omi.

The same nudges as in the app (a promise that is due, a plan that passed, an open topic), with
the same limits, only in the user's daytime, and never to chase someone who has gone quiet for
days: a greeting waits for them to write. Users with no linked channel hear it in the next return
greeting.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from agent.shared.timeline import user_zone
from channels import telegram, whatsapp
from storage import get_user_timezone, list_channel_links, list_conversations

from .policy import reach_out_hours, return_greeting_block_reason
from .service import _open_conversation, nudge_conversation

logger = logging.getLogger(__name__)

# (channel, is it switched on), looked up at call time so tests can turn one on.
CHANNELS = ((telegram.CHANNEL, telegram.telegram_enabled), (whatsapp.CHANNEL, whatsapp.whatsapp_enabled))


async def run_away_follow_ups(live_users: set[str], now: datetime) -> int:
    """Try one nudge per linked user who is not in the app; return how many went out."""
    sent = 0
    for channel, enabled in CHANNELS:
        if not enabled():
            continue
        for link in list_channel_links(channel):
            if link["user_id"] in live_users:
                continue
            try:
                if await nudge_away(link["user_id"], channel, now):
                    sent += 1
            except Exception:
                logger.exception("agent.proactive.away_failed channel=%s", channel)
    return sent


async def nudge_away(user_id: str, channel: str, now: datetime) -> bool:
    if not reach_out_hours(now, user_zone(get_user_timezone(user_id))):
        return False
    conversation = channel_conversation(user_id, channel)
    if conversation is None:
        return False
    if return_greeting_block_reason(conversation["messages"], now) is None:
        # Quiet for days: not chased on their phone.
        return False
    return await nudge_conversation(user_id, conversation, now)


async def follow_up_on_telegram(user_id: str, chat_id: str, now: datetime) -> bool:
    """Older name; the chat id now comes from the link."""
    return await nudge_away(user_id, telegram.CHANNEL, now)


def channel_conversation(user_id: str, channel: str) -> dict[str, Any] | None:
    """The user's chat with Omi on this app; None until they have written there once."""
    rows = [
        row
        for row in list_conversations(user_id)
        if row.get("channel") == channel and row.get("status") == "active" and not row.get("archived_at")
    ]
    newest = max(rows, key=lambda row: str(row.get("created_at") or ""), default=None)
    return _open_conversation(user_id, newest["id"]) if newest else None


_telegram_conversation = lambda user_id: channel_conversation(user_id, telegram.CHANNEL)  # noqa: E731  (older name)

__all__ = ["CHANNELS", "channel_conversation", "follow_up_on_telegram", "nudge_away", "run_away_follow_ups"]
