"""Stores the per-user card the companion reads on every reply."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from .database import ENGINE
from .schema import agent_user_cards
from .utils import _protect_text, _require_user_id, _unprotect_text


def get_user_card(user_id: str) -> str | None:
    owner_id = _require_user_id(user_id, "agent user card")
    with ENGINE.begin() as connection:
        value = connection.execute(
            select(agent_user_cards.c.card).where(agent_user_cards.c.user_id == owner_id)
        ).scalar_one_or_none()
    return _unprotect_text(owner_id, value) if value else None


def set_user_card(user_id: str, card: str, *, rebuilt: bool = False) -> str:
    """Save the card; `rebuilt` marks a full rewrite from all memories."""
    owner_id = _require_user_id(user_id, "agent user card")
    protected = _protect_text(owner_id, card)
    values = {"card": protected, "updated_at": func.now(), **({"rebuilt_at": func.now()} if rebuilt else {})}
    with ENGINE.begin() as connection:
        updated = connection.execute(
            agent_user_cards.update().where(agent_user_cards.c.user_id == owner_id).values(**values)
        )
        if not updated.rowcount:
            connection.execute(agent_user_cards.insert().values(user_id=owner_id, **values))
    return card


def card_rebuilt_at(user_id: str) -> datetime | None:
    owner_id = _require_user_id(user_id, "agent user card")
    with ENGINE.begin() as connection:
        value = connection.execute(
            select(agent_user_cards.c.rebuilt_at).where(agent_user_cards.c.user_id == owner_id)
        ).scalar_one_or_none()
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


__all__ = ["card_rebuilt_at", "get_user_card", "set_user_card"]
