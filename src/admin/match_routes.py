"""Operator endpoints for match pools: create a pool, see who is ready, propose pairs, record what came of them.

The pool view shows non-private vibe lines, which is more than the other admin views show; every
read is audited with the pool as the target. A pair never leaves here as it is stored: every
answer goes through operator_pair, which keeps the memory statements the judge compared and the
notes on people's answers out.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from admin.auth import require_admin_user
from agent.matching import pool_view, propose_pair
from agent.matching.asking import ask_pair, resend_undelivered
from agent.matching.hosting import PlanNotOpen, introduce_pair, set_meet_plan
from agent.matching.pick_job import start_pick
from agent.matching.pool import operator_pair, pick_run_view
from security.auth import CurrentUser
from storage import PAIR_STATUSES, create_match_pool, get_match_pool, latest_match_pick_run, list_match_pools, list_match_reports, set_match_pair_status
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
    return operator_pair(pair)


@router.post("/api/admin/pools/{pool_id}/pick", status_code=202)
async def admin_pick(pool_id: str, admin: CurrentUser = Depends(require_admin_user)) -> dict[str, object]:
    """Match day: queue the pick and return its run at once. A background job judges what needs
    judging and proposes pairs (each ready person once), a group in a thin week, and who waits;
    GET the same address for where it stands and the proposal. Picked pairs become proposed;
    nothing reaches a user until they are asked. While a run for the pool is going, that run comes back."""
    if get_match_pool(pool_id) is None:
        raise HTTPException(status_code=404, detail="Pool not found.")
    run = start_pick(pool_id, created_by=admin.id)
    record_audit_event("admin.pick_pairs", actor_id=admin.id, actor_role="admin", target_id=pool_id, detail={"run_id": run["id"]})
    return {"run": pick_run_view(run)}


@router.get("/api/admin/pools/{pool_id}/pick")
async def admin_pick_status(pool_id: str, admin: CurrentUser = Depends(require_admin_user)) -> dict[str, object]:
    """The pool's newest pick run: queued, running (with how many pairs are judged and left), done
    (with the proposal) or failed. `run` is null when the pool was never picked."""
    if get_match_pool(pool_id) is None:
        raise HTTPException(status_code=404, detail="Pool not found.")
    record_audit_event("admin.view_pick", actor_id=admin.id, actor_role="admin", target_id=pool_id)
    return {"run": pick_run_view(latest_match_pick_run(pool_id))}


@router.post("/api/admin/pairs/{pair_id}/ask")
async def admin_ask_pair(pair_id: str, admin: CurrentUser = Depends(require_admin_user)) -> dict[str, object]:
    """Omi tells both people about each other and asks each whether to introduce them."""
    try:
        pair = await ask_pair(pair_id, created_by=admin.id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Pair not found.") from None
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    record_audit_event("admin.ask_pair", actor_id=admin.id, actor_role="admin", target_id=pair_id)
    return operator_pair(pair)


@router.post("/api/admin/pairs/{pair_id}/resend")
async def admin_resend(pair_id: str, admin: CurrentUser = Depends(require_admin_user)) -> dict[str, object]:
    """Send the ask (pair asked) or the introduction (pair introduced) again to whoever it did not
    reach; a pair's `undelivered` says who that is and why. 409 when everyone was reached."""
    try:
        queued = resend_undelivered(pair_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Pair not found.") from None
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    record_audit_event("admin.resend_pair", actor_id=admin.id, actor_role="admin", target_id=pair_id, detail={"queued": len(queued)})
    return {"queued": queued}


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
    return operator_pair(pair)


@router.post("/api/admin/pairs/{pair_id}/plan")
async def admin_set_plan(pair_id: str, payload: PairIntroduction, admin: CurrentUser = Depends(require_admin_user)) -> dict[str, object]:
    """Set or change where and when an introduced pair meets, also after both said hi through the
    ask. Fields left out stay as they are. Omi tells both the plan; the reminder goes out the day
    before `meet_at` and the first check-in moves to three days after it."""
    changes = {field: getattr(payload, field) for field in payload.model_fields_set}
    if payload.meet_at is not None and payload.meet_at.utcoffset() is None:
        raise HTTPException(status_code=400, detail="meet_at needs a timezone offset.")
    try:
        pair = set_meet_plan(pair_id, changes, created_by=admin.id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Pair not found.") from None
    except PlanNotOpen as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    record_audit_event("admin.set_plan", actor_id=admin.id, actor_role="admin", target_id=pair_id, detail={"has_time": bool((pair.get("plan") or {}).get("meet_at"))})
    return operator_pair(pair)


@router.get("/api/admin/match-reports")
async def admin_match_reports(admin: CurrentUser = Depends(require_admin_user)) -> dict[str, object]:
    """What people reported about a match, newest first: who, about whom, the reason and their note.
    Never the chat between the two."""
    record_audit_event("admin.view_match_reports", actor_id=admin.id, actor_role="admin")
    return {"reports": list_match_reports()}


@router.patch("/api/admin/pairs/{pair_id}")
async def admin_pair_status(pair_id: str, payload: PairStatus, admin: CurrentUser = Depends(require_admin_user)) -> dict[str, object]:
    if payload.status not in PAIR_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {', '.join(PAIR_STATUSES)}")
    pair = set_match_pair_status(pair_id, payload.status)
    if pair is None:
        raise HTTPException(status_code=404, detail="Pair not found.")
    record_audit_event("admin.pair_status", actor_id=admin.id, actor_role="admin", target_id=pair_id, detail={"status": payload.status})
    return operator_pair(pair)
