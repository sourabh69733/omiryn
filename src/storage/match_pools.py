"""Match pools, their members and the pairs an operator proposed."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select

from agent.shared.clock import utc_now
from security.encryption import decrypt_json, maybe_encrypt_json

from .database import ENGINE
from .schema import match_pairs, match_pick_runs, match_pool_members, match_pools
from .utils import _isoformat_utc, _require_user_id

# candidate: judged by the pick, not picked. proposed: picked, waiting for the operator. asked: both
# people have been (or are being) asked. expired: the ask lapsed unanswered.
PAIR_STATUSES = ("candidate", "proposed", "asked", "introduced", "met", "no_show", "declined", "still_talking", "expired")
PICK_RUN_STATUSES = ("queued", "running", "done", "failed")
PICK_RUN_OPEN = ("queued", "running")
# The job says a run is alive at least once a minute; one silent this long has lost its worker.
PICK_RUN_STALE = timedelta(minutes=30)


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


def save_match_pair(pool_id: str, user_a: str, user_b: str, check: dict[str, Any], *, created_by: str | None = None, status: str = "proposed") -> dict[str, Any]:
    if status not in PAIR_STATUSES:
        raise ValueError(f"unknown pair status: {status}")
    pair_id = str(uuid4())
    now = utc_now()
    with ENGINE.begin() as connection:
        connection.execute(
            match_pairs.insert().values(
                id=pair_id, pool_id=pool_id, user_a=user_a, user_b=user_b, status=status,
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


def set_match_pair_plan(pair_id: str, plan: dict[str, Any], *, status: str | None = None, introduced_at: datetime | None = None) -> dict[str, Any] | None:
    """Store the meet plan (place, time, who was told); optionally the status and introduction time with it."""
    with ENGINE.begin() as connection:
        row = connection.execute(select(match_pairs.c.user_a).where(match_pairs.c.id == pair_id)).first()
        if row is None:
            return None
        values: dict[str, Any] = {"plan_json": maybe_encrypt_json(row[0], plan), "updated_at": utc_now()}
        if status is not None:
            if status not in PAIR_STATUSES:
                raise ValueError(f"unknown pair status: {status}")
            values["status"] = status
        if introduced_at is not None:
            values["introduced_at"] = introduced_at
        connection.execute(match_pairs.update().where(match_pairs.c.id == pair_id).values(**values))
    return get_match_pair(pair_id)


def update_match_pair_plan(
    pair_id: str,
    change: Callable[[dict[str, Any]], dict[str, Any] | None],
    *,
    status: str | Callable[[dict[str, Any]], str | None] | None = None,
    introduced_at: datetime | None = None,
    only_if_status: str | None = None,
) -> dict[str, Any] | None:
    """Change the plan under a row lock: `change` gets the stored plan and returns the new one (None keeps it).

    Two jobs (one per user) record that they told their user at about the same time; each reads the
    newest plan inside the lock, so neither note is lost.

    `status` may be a function of the changed plan, so a step that depends on what is stored (both
    said yes) is decided and written inside the same lock. `introduced_at` is written only when the
    pair becomes introduced. With `only_if_status` nothing runs and nothing is written unless the
    pair is at that status when the lock is taken; the pair comes back as it is.
    """
    with ENGINE.begin() as connection:
        row = connection.execute(select(match_pairs).where(match_pairs.c.id == pair_id).with_for_update()).mappings().first()
        if row is None:
            return None
        if only_if_status is not None and row["status"] != only_if_status:
            return _pair(row)
        plan = decrypt_json(row["user_a"], row["plan_json"]) if row["plan_json"] is not None else {}
        changed = change(dict(plan or {}))
        values: dict[str, Any] = {"updated_at": utc_now()}
        if changed is not None:
            values["plan_json"] = maybe_encrypt_json(row["user_a"], changed)
        new_status = status(changed if changed is not None else dict(plan or {})) if callable(status) else status
        if new_status is not None:
            if new_status not in PAIR_STATUSES:
                raise ValueError(f"unknown pair status: {new_status}")
            values["status"] = new_status
            if new_status == "introduced" and introduced_at is not None:
                values["introduced_at"] = introduced_at
        connection.execute(match_pairs.update().where(match_pairs.c.id == pair_id).values(**values))
    return get_match_pair(pair_id)


def delete_stale_match_candidates(pool_id: str, before: datetime) -> int:
    """Drop the pool's pairs that were judged, never picked, and last touched before `before`.
    Only `candidate` rows go: a pair anyone was asked about keeps its record."""
    with ENGINE.begin() as connection:
        result = connection.execute(
            match_pairs.delete().where(match_pairs.c.pool_id == pool_id, match_pairs.c.status == "candidate", match_pairs.c.updated_at < before)
        )
    return int(result.rowcount or 0)


def start_match_pick_run(pool_id: str, *, created_by: str | None = None, now: datetime | None = None) -> tuple[dict[str, Any], bool]:
    """The pool's run that is still going, with False; else a new queued run, with True.

    One pick at a time per pool: a second request while one runs gets the same run. A run nobody
    has touched for PICK_RUN_STALE is taken for dead (its worker is gone), closed as failed, and
    a new one starts.
    """
    now = now or utc_now()
    with ENGINE.begin() as connection:
        open_run = connection.execute(
            select(match_pick_runs)
            .where(match_pick_runs.c.pool_id == pool_id, match_pick_runs.c.status.in_(PICK_RUN_OPEN))
            .order_by(match_pick_runs.c.created_at.desc())
            .with_for_update()
        ).mappings().first()
        if open_run is not None:
            touched = open_run["updated_at"]
            if touched.tzinfo is None:
                touched = touched.replace(tzinfo=now.tzinfo)
            if now - touched <= PICK_RUN_STALE:
                return _pick_run(open_run), False
            connection.execute(
                match_pick_runs.update()
                .where(match_pick_runs.c.pool_id == pool_id, match_pick_runs.c.status.in_(PICK_RUN_OPEN))
                .values(status="failed", error="stalled", updated_at=now, finished_at=now)
            )
        run_id = str(uuid4())
        connection.execute(
            match_pick_runs.insert().values(id=run_id, pool_id=pool_id, status="queued", progress_json={}, created_by=created_by, created_at=now, updated_at=now)
        )
        row = connection.execute(select(match_pick_runs).where(match_pick_runs.c.id == run_id)).mappings().one()
    return _pick_run(row), True


def get_match_pick_run(run_id: str) -> dict[str, Any] | None:
    with ENGINE.begin() as connection:
        row = connection.execute(select(match_pick_runs).where(match_pick_runs.c.id == run_id)).mappings().first()
    return _pick_run(row) if row else None


def latest_match_pick_run(pool_id: str) -> dict[str, Any] | None:
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(match_pick_runs).where(match_pick_runs.c.pool_id == pool_id).order_by(match_pick_runs.c.created_at.desc())
        ).mappings().first()
    return _pick_run(row) if row else None


def update_match_pick_run(
    run_id: str,
    *,
    status: str | None = None,
    progress: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any] | None:
    """Move a run on. With nothing given it only says the run is still alive. `progress` and
    `result` hold ids, counts and states, never what anyone said or what the judge wrote."""
    if status is not None and status not in PICK_RUN_STATUSES:
        raise ValueError(f"unknown pick run status: {status}")
    now = utc_now()
    values: dict[str, Any] = {"updated_at": now}
    if status is not None:
        values["status"] = status
        if status not in PICK_RUN_OPEN:
            values["finished_at"] = now
    if progress is not None:
        values["progress_json"] = progress
    if result is not None:
        values["result_json"] = result
    if error is not None:
        values["error"] = error[:200]
    with ENGINE.begin() as connection:
        connection.execute(match_pick_runs.update().where(match_pick_runs.c.id == run_id).values(**values))
    return get_match_pick_run(run_id)


def delete_match_data_for_user(connection, user_id: str) -> dict[str, int]:
    """Account deletion: memberships, every pair the user was in, those pairs' chats, and the
    pick runs of their pools (a run lists who waited and who was paired, by id)."""
    from .match_chat import delete_match_chat_for_user

    mine = or_(match_pairs.c.user_a == user_id, match_pairs.c.user_b == user_id)
    pair_ids = [row[0] for row in connection.execute(select(match_pairs.c.id).where(mine)).all()]
    chat = delete_match_chat_for_user(connection, user_id, pair_ids)
    pool_ids = [row[0] for row in connection.execute(select(match_pool_members.c.pool_id).where(match_pool_members.c.user_id == user_id)).all()]
    if pool_ids:
        connection.execute(match_pick_runs.delete().where(match_pick_runs.c.pool_id.in_(pool_ids), match_pick_runs.c.status.notin_(PICK_RUN_OPEN)))
    members = connection.execute(match_pool_members.delete().where(match_pool_members.c.user_id == user_id)).rowcount or 0
    pairs = connection.execute(match_pairs.delete().where(mine)).rowcount or 0
    return {"match_pool_members": int(members), "match_pairs": int(pairs), **chat}


def _pool(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"], "name": row["name"], "join_code": row["join_code"], "match_weekday": int(row["match_weekday"]),
        "created_by": row.get("created_by"), "created_at": _isoformat_utc(row["created_at"]),
    }


def _pick_run(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"], "pool_id": row["pool_id"], "status": row["status"],
        "progress": dict(row["progress_json"]) if isinstance(row["progress_json"], dict) else {},
        "result": dict(row["result_json"]) if isinstance(row["result_json"], dict) else None,
        "error": row["error"], "created_by": row.get("created_by"),
        "created_at": _isoformat_utc(row["created_at"]), "updated_at": _isoformat_utc(row["updated_at"]),
        "finished_at": _isoformat_utc(row["finished_at"]) if row.get("finished_at") else None,
    }


def _pair(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"], "pool_id": row["pool_id"], "user_a": row["user_a"], "user_b": row["user_b"], "status": row["status"],
        "check": decrypt_json(row["user_a"], row["check_json"]) if row["check_json"] is not None else None,
        "plan": decrypt_json(row["user_a"], row["plan_json"]) if row["plan_json"] is not None else None,
        "introduced_at": _isoformat_utc(row["introduced_at"]) if row.get("introduced_at") else None,
        "created_by": row.get("created_by"), "created_at": _isoformat_utc(row["created_at"]), "updated_at": _isoformat_utc(row["updated_at"]),
    }


__all__ = [
    "PAIR_STATUSES", "PICK_RUN_OPEN", "PICK_RUN_STALE", "PICK_RUN_STATUSES", "create_match_pool", "delete_match_data_for_user",
    "delete_stale_match_candidates", "get_match_pair", "get_match_pick_run", "get_match_pool", "join_match_pool", "latest_match_pick_run",
    "leave_match_pool", "list_match_pairs", "list_match_pools", "match_pairs_for_user", "match_pool_by_code", "match_pool_members_of",
    "match_pools_for_user", "save_match_pair", "set_match_pair_plan", "set_match_pair_status", "start_match_pick_run", "update_match_pair_plan",
    "update_match_pick_run",
]
