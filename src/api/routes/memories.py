"""Exposes authenticated user controls for canonical V3 memories."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from security.auth import CurrentUser, require_user
from storage import (
    delete_agent_memory,
    latest_agent_memory_reviews,
    list_agent_memories,
    list_open_questions,
    resolve_open_questions,
    review_agent_memory,
    update_agent_memory_allowed_uses,
)

from ..models import MemoryPermissionsPatch, MemoryReviewCreate


router = APIRouter()


@router.get("/api/me/memories")
async def get_me_memories(
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    stored_memories = list_agent_memories(user.id)
    reviews = latest_agent_memory_reviews(
        user.id,
        [str(memory["id"]) for memory in stored_memories],
    )
    memories = [
        _user_memory_payload(memory, reviews.get(str(memory["id"])))
        for memory in stored_memories
    ]
    return {"count": len(memories), "memories": memories}


def _user_memory_payload(
    memory: dict[str, object],
    feedback: dict[str, object] | None = None,
) -> dict[str, object]:
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
    latest_feedback = feedback or (
        memory.get("feedback") if isinstance(memory.get("feedback"), dict) else None
    )
    return {
        **{field: memory.get(field) for field in fields},
        "evidence": evidence,
        "feedback": latest_feedback,
    }


@router.patch("/api/me/memories/{memory_id}/permissions")
async def patch_me_memory_permissions(
    memory_id: str,
    payload: MemoryPermissionsPatch,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    memory = update_agent_memory_allowed_uses(
        memory_id,
        user.id,
        payload.allowed_uses,
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found.")
    feedback = latest_agent_memory_reviews(user.id, [memory_id]).get(memory_id)
    return _user_memory_payload(memory, feedback)


@router.post("/api/me/memories/{memory_id}/review")
async def review_me_memory(
    memory_id: str,
    payload: MemoryReviewCreate,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    try:
        memory = review_agent_memory(
            memory_id,
            user.id,
            payload.rating,
            reasons=payload.reasons,
            comment=payload.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found.")
    return _user_memory_payload(memory)


@router.get("/api/me/open-questions")
async def get_me_open_questions(
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    """What Omi is unsure about; the user answers in chat or dismisses it here."""
    questions = [
        {key: question[key] for key in ("id", "text", "about_memory_ids", "created_at")}
        for question in list_open_questions(user.id)
    ]
    return {"questions": questions}


@router.post("/api/me/open-questions/{question_id}/dismiss")
async def dismiss_me_open_question(
    question_id: str,
    user: CurrentUser = Depends(require_user),
) -> dict[str, str]:
    if not resolve_open_questions(user.id, [(question_id, "dropped")]):
        raise HTTPException(status_code=404, detail="Question not found.")
    return {"question_id": question_id, "status": "dropped"}


@router.delete("/api/me/memories/{memory_id}")
async def delete_me_memory(
    memory_id: str,
    user: CurrentUser = Depends(require_user),
) -> dict[str, str]:
    if not delete_agent_memory(memory_id, user.id):
        raise HTTPException(status_code=404, detail="Memory not found.")
    return {"memory_id": memory_id, "status": "deleted"}


__all__ = ["router"]
