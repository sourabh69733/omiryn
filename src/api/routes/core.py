from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agent.config import agent_pipeline_config
from agent.context_engine.prompt_engine.registry import get_prompt_behavior_version
from agent.providers import agent_runtime_status
from security.auth import CurrentUser, current_user, public_auth_config

from ..helpers import _auth_user_payload, _profile_debug_data_enabled

router = APIRouter()


@router.get("/health")
def health() -> dict[str, object]:
    """Liveness plus which agent is running, so a deploy on the wrong pipeline is seen at once."""
    try:
        config = agent_pipeline_config()
        pipeline: object = {"version": config.version, "memory_contract": config.memory_contract_version}
    except ValueError as error:  # a bad env value must not take the health check down
        pipeline = {"error": str(error)}
    return {
        "status": "ok",
        "pipeline": pipeline,
        # The version actually used; an unknown AGENT_BEHAVIOR_VERSION falls back to the default.
        "prompt_version": get_prompt_behavior_version().version_id,
    }


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
