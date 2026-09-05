"""Exposes authenticated user controls for canonical V3 memories."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from security.auth import CurrentUser, require_user
from storage import delete_agent_memory


router = APIRouter()


@router.delete("/api/me/memories/{memory_id}")
async def delete_me_memory(
    memory_id: str,
    user: CurrentUser = Depends(require_user),
) -> dict[str, str]:
    if not delete_agent_memory(memory_id, user.id):
        raise HTTPException(status_code=404, detail="Memory not found.")
    return {"memory_id": memory_id, "status": "deleted"}


__all__ = ["router"]
