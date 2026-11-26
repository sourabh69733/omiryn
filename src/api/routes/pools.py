"""A user joins the match pool of their building or group with its code, and sees the pairs Omi
has told them about. A pair the pick only judged, or one waiting for the operator, is not shown:
its being there would tell them a match is coming before Omi has said a word."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agent.matching.asking import heard_about
from security.auth import CurrentUser, require_user
from storage import join_match_pool, leave_match_pool, match_pairs_for_user, match_pools_for_user

from ..helpers import _user_id

router = APIRouter()


class PoolJoin(BaseModel):
    code: str = Field(min_length=4, max_length=12)


@router.get("/api/me/pools")
async def my_pools(user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    user_id = _user_id(user)
    pools = [{k: v for k, v in pool.items() if k != "join_code"} for pool in match_pools_for_user(user_id)]
    pairs = [
        {"id": pair["id"], "pool_id": pair["pool_id"], "status": pair["status"], "created_at": pair["created_at"]}
        for pair in match_pairs_for_user(user_id)
        if heard_about(user_id, pair)
    ]
    return {"pools": pools, "pairs": pairs}


@router.post("/api/me/pools/join")
async def join_pool(payload: PoolJoin, user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    pool = join_match_pool(_user_id(user), payload.code)
    if pool is None:
        raise HTTPException(status_code=404, detail="That code does not match any group.")
    return {"pool": {k: v for k, v in pool.items() if k != "join_code"}}


@router.delete("/api/me/pools/{pool_id}")
async def leave_pool(pool_id: str, user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    return {"left": leave_match_pool(_user_id(user), pool_id)}
