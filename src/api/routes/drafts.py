from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from security.auth import CurrentUser, require_user
from storage import save_draft

from ..helpers import _apply_dating_basics, _get_existing_draft, _user_id
from ..models import AgentProfileSubmission, DraftPatch, DraftProfile

router = APIRouter()


@router.post("/api/agent-submissions/profile", status_code=201)
async def submit_agent_profile(
    submission: AgentProfileSubmission,
    user: CurrentUser = Depends(require_user),
) -> dict[str, str]:
    _apply_dating_basics(submission, user)
    draft_id = str(uuid4())
    save_draft(
        DraftProfile(id=draft_id, status="draft", submission=submission).model_dump(mode="json"),
        _user_id(user),
    )

    return {
        "draft_id": draft_id,
        "status": "draft",
        "review_url": f"/drafts/{draft_id}",
    }


@router.get("/api/drafts/{draft_id}")
async def get_draft(
    draft_id: str,
    user: CurrentUser = Depends(require_user),
) -> DraftProfile:
    return _get_existing_draft(draft_id, user)


@router.patch("/api/drafts/{draft_id}")
async def update_draft(
    draft_id: str,
    patch: DraftPatch,
    user: CurrentUser = Depends(require_user),
) -> DraftProfile:
    draft = _get_existing_draft(draft_id, user)
    if draft.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft profiles can be edited.")

    data = draft.submission.model_copy(deep=True)

    if patch.display_name is not None:
        data.display_name = patch.display_name
    if patch.gender is not None:
        data.gender.value = patch.gender
        data.gender.source = "user_stated"
        data.gender.confidence = 1
    if patch.interested_in is not None:
        data.interested_in.value = patch.interested_in
        data.interested_in.source = "user_stated"
        data.interested_in.confidence = 1
    if patch.city is not None:
        data.city.value = patch.city
        data.city.source = "user_stated"
        data.city.confidence = 1
    if patch.relationship_intent is not None:
        data.relationship_intent.value = patch.relationship_intent
        data.relationship_intent.source = "user_stated"
        data.relationship_intent.confidence = 1
    if patch.communication_style is not None:
        data.communication_style.value = patch.communication_style
        data.communication_style.source = "user_stated"
        data.communication_style.confidence = 1
    if patch.family_expectations is not None:
        data.family_expectations.value = patch.family_expectations
        data.family_expectations.source = "user_stated"
        data.family_expectations.confidence = 1
    if patch.children_preference is not None:
        data.children_preference.value = patch.children_preference
        data.children_preference.source = "user_stated"
        data.children_preference.confidence = 1
    if patch.values is not None:
        data.values.values = patch.values
        data.values.source = "user_stated"
        data.values.confidence = 1
    if patch.lifestyle is not None:
        data.lifestyle.values = patch.lifestyle
        data.lifestyle.source = "user_stated"
        data.lifestyle.confidence = 1
    if patch.dealbreakers is not None:
        data.dealbreakers.values = patch.dealbreakers
        data.dealbreakers.source = "user_stated"
        data.dealbreakers.confidence = 1
    if patch.soft_preferences is not None:
        data.soft_preferences.values = patch.soft_preferences
        data.soft_preferences.source = "user_stated"
        data.soft_preferences.confidence = 1
    if patch.summary is not None:
        data.summary = patch.summary

    updated = DraftProfile(id=draft.id, status=draft.status, submission=data)
    save_draft(updated.model_dump(mode="json"), _user_id(user))
    return updated


@router.post("/api/drafts/{draft_id}/approve")
async def approve_draft(
    draft_id: str,
    user: CurrentUser = Depends(require_user),
) -> DraftProfile:
    draft = _get_existing_draft(draft_id, user)
    if draft.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft profiles can be approved.")

    approved = DraftProfile(id=draft.id, status="approved", submission=draft.submission)
    save_draft(approved.model_dump(mode="json"), _user_id(user))
    return approved


@router.delete("/api/drafts/{draft_id}")
async def delete_draft(
    draft_id: str,
    user: CurrentUser = Depends(require_user),
) -> dict[str, str]:
    draft = _get_existing_draft(draft_id, user)
    save_draft(
        DraftProfile(id=draft.id, status="deleted", submission=draft.submission).model_dump(
            mode="json"
        ),
        _user_id(user),
    )
    return {"draft_id": draft_id, "status": "deleted"}
