"""Lets a user control whether the agent may start a conversation, and which model replies."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent.providers.shared.model_catalog import model_choices
from security.auth import CurrentUser, require_user
from storage import get_proactive_enabled, get_reply_model, set_proactive_enabled, set_reply_model

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


class ReplyModelSetting(BaseModel):
    # None goes back to the app default.
    model: str | None = None


@router.get("/api/agent/settings/model")
def read_reply_model_setting(user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    catalog = model_choices()
    picked = get_reply_model(user.id)
    offered = {choice["id"] for choice in catalog["choices"]}
    return {**catalog, "selected": picked if picked in offered else None}


@router.put("/api/agent/settings/model")
def update_reply_model_setting(
    payload: ReplyModelSetting,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    catalog = model_choices()
    if payload.model is not None and payload.model not in {choice["id"] for choice in catalog["choices"]}:
        raise HTTPException(status_code=400, detail="That model isn't offered.")
    return {**catalog, "selected": set_reply_model(user.id, payload.model)}
