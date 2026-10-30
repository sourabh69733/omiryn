"""Which chats have a web socket open, on which server instance. Shared across instances.

A row is written when a socket subscribes to a chat and removed when it leaves; the instance
refreshes its rows on a heartbeat, so rows of a crashed instance go stale and stop counting.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .database import ENGINE
from .schema import live_presence

# A row not refreshed for this long belongs to an instance that is gone.
PRESENCE_STALE_SECONDS = 60.0


def mark_live(instance_id: str, user_id: str, conversation_id: str, *, now: datetime) -> None:
    with ENGINE.begin() as connection:
        updated = connection.execute(
            live_presence.update()
            .where(
                live_presence.c.instance_id == instance_id,
                live_presence.c.user_id == user_id,
                live_presence.c.conversation_id == conversation_id,
            )
            .values(seen_at=now)
        )
        if updated.rowcount:
            return
        try:
            with connection.begin_nested():
                connection.execute(
                    live_presence.insert().values(
                        instance_id=instance_id, user_id=user_id, conversation_id=conversation_id, seen_at=now
                    )
                )
        except IntegrityError:
            pass


def clear_live(instance_id: str, user_id: str | None = None, conversation_id: str | None = None) -> None:
    """Remove this instance's rows: one chat, one user's chats, or all of them."""
    conditions = [live_presence.c.instance_id == instance_id]
    if user_id is not None:
        conditions.append(live_presence.c.user_id == user_id)
    if conversation_id is not None:
        conditions.append(live_presence.c.conversation_id == conversation_id)
    with ENGINE.begin() as connection:
        connection.execute(live_presence.delete().where(*conditions))


def refresh_live(instance_id: str, pairs: list[tuple[str, str]], *, now: datetime) -> None:
    """The heartbeat: the rows this instance still has sockets for stay fresh; the rest go."""
    with ENGINE.begin() as connection:
        connection.execute(live_presence.delete().where(live_presence.c.instance_id == instance_id))
        if pairs:
            connection.execute(
                live_presence.insert(),
                [
                    {"instance_id": instance_id, "user_id": user_id, "conversation_id": conversation_id, "seen_at": now}
                    for user_id, conversation_id in pairs
                ],
            )


def live_conversations_everywhere(*, now: datetime, within_seconds: float = PRESENCE_STALE_SECONDS) -> dict[tuple[str, str], set[str]]:
    """(user_id, conversation_id) -> the instances with a socket on it, fresh rows only."""
    cutoff = now - timedelta(seconds=within_seconds)
    with ENGINE.begin() as connection:
        rows = connection.execute(
            select(live_presence.c.user_id, live_presence.c.conversation_id, live_presence.c.instance_id).where(
                live_presence.c.seen_at >= cutoff
            )
        ).all()
    live: dict[tuple[str, str], set[str]] = {}
    for user_id, conversation_id, instance_id in rows:
        live.setdefault((user_id, conversation_id), set()).add(instance_id)
    return live


__all__ = ["PRESENCE_STALE_SECONDS", "clear_live", "live_conversations_everywhere", "mark_live", "refresh_live"]
