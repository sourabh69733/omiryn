"""Stores per-user agent preferences that the user controls."""

from __future__ import annotations

from sqlalchemy import func, select

from .database import ENGINE
from .schema import agent_user_settings
from .utils import _require_user_id


def get_proactive_enabled(user_id: str) -> bool:
    """Agent-initiated messages are on unless the user has switched them off."""
    owner_id = _require_user_id(user_id, "agent user settings")
    with ENGINE.begin() as connection:
        value = connection.execute(
            select(agent_user_settings.c.proactive_enabled).where(
                agent_user_settings.c.user_id == owner_id
            )
        ).scalar_one_or_none()
    return True if value is None else bool(value)


def set_proactive_enabled(user_id: str, enabled: bool) -> bool:
    owner_id = _require_user_id(user_id, "agent user settings")
    with ENGINE.begin() as connection:
        updated = connection.execute(
            agent_user_settings.update()
            .where(agent_user_settings.c.user_id == owner_id)
            .values(proactive_enabled=enabled, updated_at=func.now())
        )
        if not updated.rowcount:
            connection.execute(
                agent_user_settings.insert().values(
                    user_id=owner_id, proactive_enabled=enabled
                )
            )
    return enabled


def get_user_timezone(user_id: str) -> str | None:
    """Return the browser-reported IANA timezone, or None if never reported."""
    owner_id = _require_user_id(user_id, "agent user settings")
    with ENGINE.begin() as connection:
        return connection.execute(
            select(agent_user_settings.c.timezone).where(
                agent_user_settings.c.user_id == owner_id
            )
        ).scalar_one_or_none()


def set_user_timezone(user_id: str, timezone_name: str) -> str:
    """Store an already validated IANA timezone name."""
    owner_id = _require_user_id(user_id, "agent user settings")
    with ENGINE.begin() as connection:
        updated = connection.execute(
            agent_user_settings.update()
            .where(agent_user_settings.c.user_id == owner_id)
            .values(timezone=timezone_name, updated_at=func.now())
        )
        if not updated.rowcount:
            connection.execute(
                agent_user_settings.insert().values(
                    user_id=owner_id, proactive_enabled=True, timezone=timezone_name
                )
            )
    return timezone_name
