from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agent.runtime.providers import agent_runtime_status
from security.auth import CurrentUser, current_user, public_auth_config

from ..helpers import _auth_user_payload, _profile_debug_data_enabled

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/agent/status")
def agent_status() -> dict[str, object]:
    return agent_runtime_status()


@router.get("/api/auth/config")
def auth_config() -> dict[str, object]:
    return {
        **public_auth_config(),
        "profile_debug_data_enabled": _profile_debug_data_enabled(),
    }


@router.get("/api/auth/me")
async def auth_me(user: CurrentUser | None = Depends(current_user)) -> dict[str, str | None]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return _auth_user_payload(user)

