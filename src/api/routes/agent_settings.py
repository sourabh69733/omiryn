"""Lets a user control whether the agent may start a conversation."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from security.auth import CurrentUser, require_user
from storage import get_proactive_enabled, set_proactive_enabled

router = APIRouter()


class ProactiveSetting(BaseModel):
    proactive_enabled: bool


@router.get("/api/agent/settings/proactive")
def read_proactive_setting(user: CurrentUser = Depends(require_user)) -> ProactiveSetting:
    return ProactiveSetting(proactive_enabled=get_proactive_enabled(user.id))


@router.put("/api/agent/settings/proactive")
def update_proactive_setting(
    payload: ProactiveSetting,
    user: CurrentUser = Depends(require_user),
) -> ProactiveSetting:
    return ProactiveSetting(
        proactive_enabled=set_proactive_enabled(user.id, payload.proactive_enabled)
    )
