"""Links a messaging app chat (Telegram today) to an Omiryn account."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select

from agent.shared.clock import utc_now

from .database import ENGINE
from .schema import channel_link_codes, channel_links
from .utils import _isoformat_utc, _require_user_id

# Long enough to switch to the messaging app and tap Start.
CHANNEL_LINK_CODE_TTL = timedelta(minutes=15)


def create_channel_link_code(user_id: str, channel: str) -> tuple[str, datetime]:
    """A new one-time code for this user; earlier unused codes stop working."""
    owner_id = _require_user_id(user_id, "channel link code")
    # Telegram start payloads allow A-Z, a-z, 0-9, _ and -, up to 64 characters.
    code = secrets.token_urlsafe(24)
    expires_at = utc_now() + CHANNEL_LINK_CODE_TTL
    with ENGINE.begin() as connection:
        connection.execute(
            channel_link_codes.delete().where(
                channel_link_codes.c.user_id == owner_id,
                channel_link_codes.c.channel == channel,
            )
        )
        connection.execute(
            channel_link_codes.insert().values(
                code_hash=_code_hash(code),
                user_id=owner_id,
                channel=channel,
                expires_at=expires_at,
            )
        )
    return code, expires_at


def consume_channel_link_code(code: str, channel: str) -> str | None:
    """The user the code belongs to, or None when it is unknown or expired. A code works once."""
    if not code:
        return None
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(channel_link_codes).where(
                channel_link_codes.c.code_hash == _code_hash(code),
                channel_link_codes.c.channel == channel,
            )
        ).mappings().first()
        if row is None:
            return None
        connection.execute(
            channel_link_codes.delete().where(channel_link_codes.c.code_hash == row["code_hash"])
        )
    if _aware(row["expires_at"]) <= utc_now():
        return None
    return str(row["user_id"])


def link_channel_chat(user_id: str, channel: str, external_chat_id: str) -> None:
    """Point this chat at this user. A chat belongs to one account, and an account has one chat."""
    owner_id = _require_user_id(user_id, "channel link")
    with ENGINE.begin() as connection:
        connection.execute(
            channel_links.delete().where(
                channel_links.c.channel == channel,
                or_(
                    channel_links.c.user_id == owner_id,
                    channel_links.c.external_chat_id == external_chat_id,
                ),
            )
        )
        connection.execute(
            channel_links.insert().values(
                user_id=owner_id, channel=channel, external_chat_id=external_chat_id
            )
        )


def channel_link_for_chat(channel: str, external_chat_id: str) -> dict[str, Any] | None:
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(channel_links).where(
                channel_links.c.channel == channel,
                channel_links.c.external_chat_id == external_chat_id,
            )
        ).mappings().first()
    return _link(row)


def channel_link_for_user(user_id: str, channel: str) -> dict[str, Any] | None:
    owner_id = _require_user_id(user_id, "channel link")
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(channel_links).where(
                channel_links.c.user_id == owner_id,
                channel_links.c.channel == channel,
            )
        ).mappings().first()
    return _link(row)


def list_channel_links(channel: str) -> list[dict[str, Any]]:
    """Every account linked on this channel; Omi can reach these users there while they are away."""
    with ENGINE.begin() as connection:
        rows = connection.execute(
            select(channel_links).where(channel_links.c.channel == channel)
        ).mappings().all()
    return [link for row in rows if (link := _link(row))]


def unlink_channel(user_id: str, channel: str) -> dict[str, Any] | None:
    """Remove the link; returns the removed link so the caller can say goodbye in that chat."""
    link = channel_link_for_user(user_id, channel)
    if link is None:
        return None
    with ENGINE.begin() as connection:
        connection.execute(
            channel_links.delete().where(
                channel_links.c.user_id == link["user_id"],
                channel_links.c.channel == channel,
            )
        )
    return link


def claim_channel_update(channel: str, external_chat_id: str, update_id: int) -> bool:
    """True the first time an update is seen for a linked chat; False for a retried delivery."""
    with ENGINE.begin() as connection:
        result = connection.execute(
            channel_links.update()
            .where(
                channel_links.c.channel == channel,
                channel_links.c.external_chat_id == external_chat_id,
                or_(
                    channel_links.c.last_update_id.is_(None),
                    channel_links.c.last_update_id < update_id,
                ),
            )
            .values(last_update_id=update_id)
        )
    return bool(result.rowcount)


def _link(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "user_id": row["user_id"],
        "channel": row["channel"],
        "external_chat_id": row["external_chat_id"],
        "created_at": _isoformat_utc(row["created_at"]),
    }


def _code_hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _aware(value: datetime) -> datetime:
    # SQLite hands back naive datetimes; they were written in UTC.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


__all__ = [
    "CHANNEL_LINK_CODE_TTL",
    "channel_link_for_chat",
    "channel_link_for_user",
    "claim_channel_update",
    "consume_channel_link_code",
    "create_channel_link_code",
    "link_channel_chat",
    "list_channel_links",
    "unlink_channel",
]
