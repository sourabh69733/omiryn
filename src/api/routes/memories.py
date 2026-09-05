"""Exposes authenticated user controls for canonical V3 memories."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from security.auth import CurrentUser, require_user
from storage import delete_agent_memory, list_agent_memories


router = APIRouter()


@router.get("/api/me/memories")
async def get_me_memories(
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    memories = [_user_memory_payload(memory) for memory in list_agent_memories(user.id)]
    return {"count": len(memories), "memories": memories}


def _user_memory_payload(memory: dict[str, object]) -> dict[str, object]:
    """Expose user-controlled memory fields without runtime implementation details."""
    fields = (
        "id",
        "kind",
        "purposes",
        "key",
        "value",
        "allowed_uses",
        "status",
        "sensitivity",
        "confidence",
        "importance",
        "occurred_at",
        "valid_from",
        "valid_until",
        "last_reinforced_at",
        "supersedes_memory_id",
        "created_at",
        "updated_at",
    )
    evidence_fields = (
        "conversation_id",
        "message_id",
        "message_index",
        "exact_quote",
        "observed_at",
    )
    evidence = [
        {field: item.get(field) for field in evidence_fields}
        for item in memory.get("evidence") or []
        if isinstance(item, dict)
    ]
    return {**{field: memory.get(field) for field in fields}, "evidence": evidence}


@router.delete("/api/me/memories/{memory_id}")
async def delete_me_memory(
    memory_id: str,
    user: CurrentUser = Depends(require_user),
) -> dict[str, str]:
    if not delete_agent_memory(memory_id, user.id):
        raise HTTPException(status_code=404, detail="Memory not found.")
    return {"memory_id": memory_id, "status": "deleted"}


__all__ = ["router"]
