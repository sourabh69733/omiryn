"""Match pools, their members and the pairs an operator proposed."""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select

from agent.shared.clock import utc_now
from security.encryption import decrypt_json, maybe_encrypt_json

from .database import ENGINE
from .schema import match_pairs, match_pool_members, match_pools
from .utils import _isoformat_utc, _require_user_id

PAIR_STATUSES = ("proposed", "introduced", "met", "no_show", "declined", "still_talking")


def create_match_pool(name: str, *, match_weekday: int = 6, created_by: str | None = None) -> dict[str, Any]:
    pool_id = str(uuid4())
    # Short, typeable, no ambiguous letters: what a resident sends to the number.
    code = "".join(secrets.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(6))
    with ENGINE.begin() as connection:
        connection.execute(
            match_pools.insert().values(id=pool_id, name=name.strip()[:80], join_code=code, match_weekday=int(match_weekday) % 7, created_by=created_by)
        )
    return get_match_pool(pool_id)  # type: ignore[return-value]


def get_match_pool(pool_id: str) -> dict[str, Any] | None:
    with ENGINE.begin() as connection:
        row = connection.execute(select(match_pools).where(match_pools.c.id == pool_id)).mappings().first()
    return _pool(row) if row else None


def match_pool_by_code(code: str) -> dict[str, Any] | None:
    with ENGINE.begin() as connection:
        row = connection.execute(select(match_pools).where(match_pools.c.join_code == code.strip().lower())).mappings().first()
    return _pool(row) if row else None


def list_match_pools() -> list[dict[str, Any]]:
    with ENGINE.begin() as connection:
        rows = connection.execute(select(match_pools).order_by(match_pools.c.created_at.desc())).mappings().all()
        counts = dict(
            connection.execute(
                select(match_pool_members.c.pool_id, func.count()).where(match_pool_members.c.left_at.is_(None)).group_by(match_pool_members.c.pool_id)
            ).all()
        )
    return [{**_pool(row), "member_count": int(counts.get(row["id"], 0))} for row in rows]


def join_match_pool(user_id: str, code: str) -> dict[str, Any] | None:
    """Add the user to the pool with this code; rejoining a pool they left is fine. None: no such code."""
    owner_id = _require_user_id(user_id, "match pool member")
    pool = match_pool_by_code(code)
    if pool is None:
        return None
    with ENGINE.begin() as connection:
        existing = connection.execute(
            select(match_pool_members).where(match_pool_members.c.pool_id == pool["id"], match_pool_members.c.user_id == owner_id)
        ).mappings().first()
        if existing is None:
            connection.execute(match_pool_members.insert().values(pool_id=pool["id"], user_id=owner_id, joined_at=utc_now()))
        elif existing["left_at"] is not None:
            connection.execute(
                match_pool_members.update()
                .where(match_pool_members.c.pool_id == pool["id"], match_pool_members.c.user_id == owner_id)
                .values(left_at=None, joined_at=utc_now())
            )
    return pool


def leave_match_pool(user_id: str, pool_id: str) -> bool:
    owner_id = _require_user_id(user_id, "match pool member")
    with ENGINE.begin() as connection:
        result = connection.execute(
            match_pool_members.update()
            .where(match_pool_members.c.pool_id == pool_id, match_pool_members.c.user_id == owner_id, match_pool_members.c.left_at.is_(None))
            .values(left_at=utc_now())
        )
    return bool(result.rowcount)


def match_pools_for_user(user_id: str) -> list[dict[str, Any]]:
    owner_id = _require_user_id(user_id, "match pool member")
    with ENGINE.begin() as connection:
        rows = connection.execute(
            select(match_pools, match_pool_members.c.joined_at)
            .join(match_pool_members, match_pool_members.c.pool_id == match_pools.c.id)
            .where(match_pool_members.c.user_id == owner_id, match_pool_members.c.left_at.is_(None))
        ).mappings().all()
    return [{**_pool(row), "joined_at": _isoformat_utc(row["joined_at"])} for row in rows]


def match_pool_members_of(pool_id: str) -> list[dict[str, Any]]:
    with ENGINE.begin() as connection:
        rows = connection.execute(
            select(match_pool_members).where(match_pool_members.c.pool_id == pool_id, match_pool_members.c.left_at.is_(None)).order_by(match_pool_members.c.joined_at.asc())
        ).mappings().all()
    return [{"user_id": row["user_id"], "joined_at": _isoformat_utc(row["joined_at"])} for row in rows]


def save_match_pair(pool_id: str, user_a: str, user_b: str, check: dict[str, Any], *, created_by: str | None = None) -> dict[str, Any]:
    pair_id = str(uuid4())
    now = utc_now()
    with ENGINE.begin() as connection:
        connection.execute(
            match_pairs.insert().values(
                id=pair_id, pool_id=pool_id, user_a=user_a, user_b=user_b, status="proposed",
                check_json=maybe_encrypt_json(user_a, check), created_by=created_by, created_at=now, updated_at=now,
            )
        )
    return get_match_pair(pair_id)  # type: ignore[return-value]


def get_match_pair(pair_id: str) -> dict[str, Any] | None:
    with ENGINE.begin() as connection:
        row = connection.execute(select(match_pairs).where(match_pairs.c.id == pair_id)).mappings().first()
    return _pair(row) if row else None


def list_match_pairs(pool_id: str) -> list[dict[str, Any]]:
    with ENGINE.begin() as connection:
        rows = connection.execute(select(match_pairs).where(match_pairs.c.pool_id == pool_id).order_by(match_pairs.c.created_at.desc())).mappings().all()
    return [_pair(row) for row in rows]


def match_pairs_for_user(user_id: str) -> list[dict[str, Any]]:
    owner_id = _require_user_id(user_id, "match pair")
    with ENGINE.begin() as connection:
        rows = connection.execute(
            select(match_pairs).where(or_(match_pairs.c.user_a == owner_id, match_pairs.c.user_b == owner_id)).order_by(match_pairs.c.created_at.desc())
        ).mappings().all()
    return [_pair(row) for row in rows]


def set_match_pair_status(pair_id: str, status: str) -> dict[str, Any] | None:
    if status not in PAIR_STATUSES:
        raise ValueError(f"unknown pair status: {status}")
    with ENGINE.begin() as connection:
        connection.execute(match_pairs.update().where(match_pairs.c.id == pair_id).values(status=status, updated_at=utc_now()))
    return get_match_pair(pair_id)


def delete_match_data_for_user(connection, user_id: str) -> dict[str, int]:
    """Account deletion: memberships and every pair the user was in."""
    members = connection.execute(match_pool_members.delete().where(match_pool_members.c.user_id == user_id)).rowcount or 0
    pairs = connection.execute(match_pairs.delete().where(or_(match_pairs.c.user_a == user_id, match_pairs.c.user_b == user_id))).rowcount or 0
    return {"match_pool_members": int(members), "match_pairs": int(pairs)}


def _pool(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"], "name": row["name"], "join_code": row["join_code"], "match_weekday": int(row["match_weekday"]),
        "created_by": row.get("created_by"), "created_at": _isoformat_utc(row["created_at"]),
    }


def _pair(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"], "pool_id": row["pool_id"], "user_a": row["user_a"], "user_b": row["user_b"], "status": row["status"],
        "check": decrypt_json(row["user_a"], row["check_json"]) if row["check_json"] is not None else None,
        "created_by": row.get("created_by"), "created_at": _isoformat_utc(row["created_at"]), "updated_at": _isoformat_utc(row["updated_at"]),
    }


__all__ = [
    "PAIR_STATUSES", "create_match_pool", "delete_match_data_for_user", "get_match_pair", "get_match_pool", "join_match_pool",
    "leave_match_pool", "list_match_pairs", "list_match_pools", "match_pairs_for_user", "match_pool_by_code", "match_pool_members_of",
    "match_pools_for_user", "save_match_pair", "set_match_pair_status",
]
