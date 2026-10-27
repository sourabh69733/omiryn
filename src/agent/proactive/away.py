"""Reaches users who are away from the app: asks how a plan went in their Telegram chat.

Only plan follow-ups go out this way, only in the user's daytime, and with the same nudge
limits as in the app. Users with no linked channel hear it in the next return greeting.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from agent.shared.timeline import user_zone
from channels.telegram import CHANNEL, send_telegram_message, telegram_enabled
from storage import get_user_timezone, list_channel_links, list_conversations

from .policy import nudge_block_reason, reach_out_hours
from .service import _due_event, _open_conversation, follow_up_event

logger = logging.getLogger(__name__)


async def run_away_follow_ups(live_users: set[str], now: datetime) -> int:
    """Try one plan follow-up per Telegram-linked user who is not in the app; return how many went out."""
    if not telegram_enabled():
        return 0
    sent = 0
    for link in list_channel_links(CHANNEL):
        if link["user_id"] in live_users:
            continue
        try:
            if await follow_up_on_telegram(link["user_id"], link["external_chat_id"], now):
                sent += 1
        except Exception:
            logger.exception("agent.proactive.away_failed")
    return sent


async def follow_up_on_telegram(user_id: str, chat_id: str, now: datetime) -> bool:
    if not reach_out_hours(now, user_zone(get_user_timezone(user_id))):
        return False
    conversation = _telegram_conversation(user_id)
    if conversation is None or nudge_block_reason(conversation["messages"], now):
        return False
    event = _due_event(user_id, now)
    if event is None:
        return False
    message = await follow_up_event(user_id, conversation, event, now)
    if message is None:
        return False
    await send_telegram_message(chat_id, message["content"])
    return True


def _telegram_conversation(user_id: str) -> dict[str, Any] | None:
    """The user's Telegram chat with Omi; None until they have written there once."""
    rows = [
        row
        for row in list_conversations(user_id)
        if row.get("channel") == CHANNEL and row.get("status") == "active" and not row.get("archived_at")
    ]
    newest = max(rows, key=lambda row: str(row.get("created_at") or ""), default=None)
    return _open_conversation(user_id, newest["id"]) if newest else None
