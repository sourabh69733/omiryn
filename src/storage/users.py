from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from .context_sources import _context_source_from_row
from .database import ENGINE
from .schema import conversation_context_sources, user_profiles
from .utils import _isoformat_utc, _owned_update_values

def get_user_profile(user_id: str) -> dict[str, Any] | None:
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(user_profiles).where(user_profiles.c.user_id == user_id)
        ).mappings().first()
    if not row:
        return None
    return {
        "user_id": row["user_id"],
        "display_name": row["display_name"],
        "age": row["age"],
        "gender": row["gender"],
        "interested_in": row["interested_in"],
        "city": row["city"],
        "region": row["region"],
        "country": row["country"],
        "location_source": row["location_source"],
        "adult_confirmed_at": _isoformat_utc(row["adult_confirmed_at"]),
        "phone": row["phone"],
        "profile_photo_url": row["profile_photo_url"],
        "profile_photo_urls": row["profile_photo_urls"] or [],
        "profile_photo_file_name": row["profile_photo_file_name"],
        "profile_photo_file_names": row["profile_photo_file_names"] or [],
        "created_at": _isoformat_utc(row["created_at"]),
        "updated_at": _isoformat_utc(row["updated_at"]),
    }


def save_setup_basics(user_id: str, display_name: str) -> dict[str, Any]:
    """The one-screen signup: a name and the 18+ confirmation; nothing else is required."""
    values = {"display_name": display_name, "adult_confirmed_at": func.now()}
    with ENGINE.begin() as connection:
        updated = connection.execute(
            user_profiles.update()
            .where(user_profiles.c.user_id == user_id)
            .values(**values, updated_at=func.now())
        )
        if not updated.rowcount:
            connection.execute(user_profiles.insert().values(user_id=user_id, **values))
    return get_user_profile(user_id) or {}


def set_estimated_location(user_id: str, place: dict[str, str]) -> None:
    """Store a location estimated from the IP, never over one the user gave us."""
    profile = get_user_profile(user_id) or {}
    if profile.get("location_source") == "user" or (
        profile.get("city") and profile.get("location_source") != "ip"
    ):
        return
    with ENGINE.begin() as connection:
        connection.execute(
            user_profiles.update()
            .where(user_profiles.c.user_id == user_id)
            .values(
                city=place.get("city"),
                region=place.get("region"),
                country=place.get("country"),
                location_source="ip",
                updated_at=func.now(),
            )
        )


def save_user_profile(
    user_id: str,
    gender: str,
    interested_in: str,
    display_name: str | None = None,
    age: int | None = None,
    city: str | None = None,
    phone: str | None = None,
    profile_photo_url: str | None = None,
    profile_photo_urls: list[str] | None = None,
    profile_photo_file_name: str | None = None,
    profile_photo_file_names: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "user_id": user_id,
        "display_name": display_name,
        "age": age,
        "gender": gender,
        "interested_in": interested_in,
        "city": city,
        "phone": phone,
        # A city typed by the user replaces any estimate from their connection.
        **({"location_source": "user"} if city else {}),
        "profile_photo_url": profile_photo_url,
        "profile_photo_urls": profile_photo_urls or ([profile_photo_url] if profile_photo_url else []),
        "profile_photo_file_name": profile_photo_file_name,
        "profile_photo_file_names": profile_photo_file_names
        or ([profile_photo_file_name] if profile_photo_file_name else []),
    }
    with ENGINE.begin() as connection:
        existing = connection.execute(
            select(user_profiles.c.user_id).where(user_profiles.c.user_id == user_id)
        ).first()
        if existing:
            connection.execute(
                user_profiles.update()
                .where(user_profiles.c.user_id == user_id)
                .values(
                    **_owned_update_values(payload, "display_name"),
                    updated_at=func.now(),
                )
            )
        else:
            connection.execute(user_profiles.insert().values(**payload))

    return get_user_profile(user_id) or payload


def list_user_context_sources(
    user_id: str,
    source_types: set[str] | None = None,
) -> list[dict[str, Any]]:
    statement = (
        select(conversation_context_sources)
        .where(conversation_context_sources.c.user_id == user_id)
        .order_by(conversation_context_sources.c.created_at.desc())
    )
    if source_types:
        statement = statement.where(conversation_context_sources.c.source_type.in_(source_types))

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_context_source_from_row(row) for row in rows]

