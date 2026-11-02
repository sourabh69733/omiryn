"""Operator endpoints for match pools: create a pool, see who is ready, propose pairs, record what came of them.

The pool view shows non-private vibe lines, which is more than the other admin views show; every
read is audited with the pool as the target.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from admin.auth import require_admin_user
from agent.matching import pool_view, propose_pair
from agent.matching.hosting import introduce_pair
from security.auth import CurrentUser
from storage import PAIR_STATUSES, create_match_pool, list_match_pools, set_match_pair_status
from storage.audit_log import record_audit_event

router = APIRouter()


class PoolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    match_weekday: int = Field(default=6, ge=0, le=6)


class PairCreate(BaseModel):
    user_a: str
    user_b: str


class PairStatus(BaseModel):
    status: str


class PairIntroduction(BaseModel):
    """The plan in the operator's words; `meet_at` (ISO 8601 with offset) times the reminder and check-in."""

    place: str | None = Field(default=None, max_length=160)
    when: str | None = Field(default=None, max_length=80)
    meet_at: datetime | None = None


@router.get("/api/admin/pools")
async def admin_pools(admin: CurrentUser = Depends(require_admin_user)) -> dict[str, object]:
    record_audit_event("admin.view_pools", actor_id=admin.id, actor_role="admin")
    return {"pools": list_match_pools()}


@router.post("/api/admin/pools", status_code=201)
async def admin_create_pool(payload: PoolCreate, admin: CurrentUser = Depends(require_admin_user)) -> dict[str, object]:
    pool = create_match_pool(payload.name, match_weekday=payload.match_weekday, created_by=admin.id)
    record_audit_event("admin.create_pool", actor_id=admin.id, actor_role="admin", target_id=pool["id"])
    return pool


@router.get("/api/admin/pools/{pool_id}")
async def admin_pool(pool_id: str, admin: CurrentUser = Depends(require_admin_user)) -> dict[str, object]:
    view = pool_view(pool_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Pool not found.")
    record_audit_event("admin.view_pool", actor_id=admin.id, actor_role="admin", target_id=pool_id)
    return view


@router.post("/api/admin/pools/{pool_id}/pairs", status_code=201)
async def admin_propose_pair(pool_id: str, payload: PairCreate, admin: CurrentUser = Depends(require_admin_user)) -> dict[str, object]:
    try:
        pair = await propose_pair(pool_id, payload.user_a, payload.user_b, created_by=admin.id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    record_audit_event("admin.propose_pair", actor_id=admin.id, actor_role="admin", target_id=pair["id"])
    return pair


@router.post("/api/admin/pairs/{pair_id}/introduce")
async def admin_introduce_pair(pair_id: str, payload: PairIntroduction, admin: CurrentUser = Depends(require_admin_user)) -> dict[str, object]:
    """Omi tells both people about each other in their own chats, with the plan; reminder and check-ins follow."""
    if payload.meet_at is not None and payload.meet_at.utcoffset() is None:
        raise HTTPException(status_code=400, detail="meet_at needs a timezone offset.")
    try:
        pair = await introduce_pair(pair_id, place=payload.place, when=payload.when, meet_at=payload.meet_at, created_by=admin.id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Pair not found.") from None
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    record_audit_event("admin.introduce_pair", actor_id=admin.id, actor_role="admin", target_id=pair_id, detail={"has_time": payload.meet_at is not None})
    return pair


@router.patch("/api/admin/pairs/{pair_id}")
async def admin_pair_status(pair_id: str, payload: PairStatus, admin: CurrentUser = Depends(require_admin_user)) -> dict[str, object]:
    if payload.status not in PAIR_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {', '.join(PAIR_STATUSES)}")
    pair = set_match_pair_status(pair_id, payload.status)
    if pair is None:
        raise HTTPException(status_code=404, detail="Pair not found.")
    record_audit_event("admin.pair_status", actor_id=admin.id, actor_role="admin", target_id=pair_id, detail={"status": payload.status})
    return pair
