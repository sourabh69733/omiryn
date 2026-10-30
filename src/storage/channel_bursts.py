"""Shared state for messaging-app replies: bursts of quick messages, and deliveries already seen.

Both used to live in one server process; here several instances agree on them.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .database import ENGINE
from .schema import channel_bursts, channel_seen_messages
from .utils import _isoformat_utc


def join_burst(
    channel: str,
    external_chat_id: str,
    conversation_id: str,
    *,
    now: datetime,
    lease_seconds: float,
) -> dict[str, Any]:
    """Count a message into the chat's burst. Returns the burst state plus `token` when this
    caller won the replier lease (nobody is answering, or the last replier's lease expired)."""
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(channel_bursts)
            .where(channel_bursts.c.channel == channel, channel_bursts.c.external_chat_id == external_chat_id)
            .with_for_update()
        ).mappings().first()
        token = None
        if row is None:
            token = str(uuid4())
            values = {
                "channel": channel,
                "external_chat_id": external_chat_id,
                "conversation_id": conversation_id,
                "arrivals": 1,
                "last_at": now,
                "replier_token": token,
                "replier_until": now + timedelta(seconds=lease_seconds),
            }
            connection.execute(channel_bursts.insert().values(**values))
            arrivals = 1
        else:
            arrivals = int(row["arrivals"]) + 1
            values = {"arrivals": arrivals, "last_at": now}
            expired = row["replier_until"] is None or _aware(row["replier_until"]) <= now
            if not row["replier_token"] or expired:
                token = str(uuid4())
                values.update(replier_token=token, replier_until=now + timedelta(seconds=lease_seconds))
            connection.execute(
                channel_bursts.update()
                .where(channel_bursts.c.channel == channel, channel_bursts.c.external_chat_id == external_chat_id)
                .values(**values)
            )
    return {"arrivals": arrivals, "last_at": now, "token": token}


def burst_state(channel: str, external_chat_id: str) -> dict[str, Any] | None:
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(channel_bursts.c.arrivals, channel_bursts.c.last_at).where(
                channel_bursts.c.channel == channel, channel_bursts.c.external_chat_id == external_chat_id
            )
        ).mappings().first()
    if row is None:
        return None
    return {"arrivals": int(row["arrivals"]), "last_at": _aware(row["last_at"])}


def finish_burst(channel: str, external_chat_id: str, token: str, *, answered: int) -> bool:
    """Close the burst once every counted message is answered. False when more arrived since
    `answered` (the replier goes round again) or the lease is no longer this caller's."""
    with ENGINE.begin() as connection:
        result = connection.execute(
            channel_bursts.delete().where(
                channel_bursts.c.channel == channel,
                channel_bursts.c.external_chat_id == external_chat_id,
                channel_bursts.c.replier_token == token,
                channel_bursts.c.arrivals == answered,
            )
        )
    return bool(result.rowcount)


def release_burst(channel: str, external_chat_id: str, token: str) -> None:
    """Give the lease up without answering (the reply failed): the next message claims it."""
    with ENGINE.begin() as connection:
        connection.execute(
            channel_bursts.delete().where(
                channel_bursts.c.channel == channel,
                channel_bursts.c.external_chat_id == external_chat_id,
                channel_bursts.c.replier_token == token,
            )
        )


def claim_channel_message(channel: str, message_id: str) -> bool:
    """True the first time this delivery is seen; False for a repeat."""
    if not message_id:
        return True
    try:
        with ENGINE.begin() as connection:
            connection.execute(channel_seen_messages.insert().values(channel=channel, message_id=message_id))
    except IntegrityError:
        return False
    return True


def _aware(value: datetime) -> datetime:
    from datetime import UTC

    return value if value.tzinfo else value.replace(tzinfo=UTC)


__all__ = ["burst_state", "claim_channel_message", "finish_burst", "join_burst", "release_burst"]
