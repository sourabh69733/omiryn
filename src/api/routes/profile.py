from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from agent.context_engine.context import STYLE_CONTEXT_SOURCE_TYPES
from agent.memory_engine.data_point_feedback import normalize_data_point_feedback
from security.auth import CurrentUser, require_user
from storage import (
    delete_profile_fact,
    delete_user_private_data,
    get_profile_fact,
    get_user_profile,
    save_app_events,
    list_user_data_requests,
    list_data_point_feedback,
    list_profile_facts,
    list_user_context_sources,
    save_data_request,
    save_data_point_feedback,
    save_feedback_submission,
    save_user_profile,
    update_profile_fact_user_correction,
)

from ..config import PROFILE_PHOTO_CONTENT_TYPES, PROFILE_PHOTO_MAX_BYTES, PROFILE_PHOTO_MAX_COUNT
from ..helpers import (
    _auth_user_payload,
    _basic_profile_complete,
    _clean_optional_text,
    _context_source_summary,
    _data_point_feedback_summary_for_fact,
    _delete_profile_photo_file_names,
    _dedupe_context_sources,
    _group_profile_facts,
    _latest_data_point_feedback_by_fact,
    _profile_debug_data_enabled,
    _profile_facts_with_feedback,
    _profile_with_auth_defaults,
    _raw_profile_data_points,
    _reusable_context_sources,
    _store_profile_photo,
    _summarize_data_point_feedback,
    logger,
)
from ..models import (
    AppEventsBatchCreate,
    CommunityInviteRequestCreate,
    DataPointFeedbackCreate,
    DataRequestCreate,
    DatingBasics,
    FeedbackSubmissionCreate,
    ProfileFactPatch,
    UserProfilePatch,
)
router = APIRouter()

_APP_EVENT_METADATA_ALLOWLIST = {
    "conversation_id",
    "fact_category",
    "source_type",
    "request_type",
    "area",
    "message_code",
    "page",
    "category",
    "channel",
}


@router.get("/api/me/dating-basics")
async def get_dating_basics(
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    profile = _profile_with_auth_defaults(get_user_profile(user.id), user)
    return {
        "complete": _basic_profile_complete(profile),
        "profile": profile,
    }


@router.put("/api/me/dating-basics")
async def put_dating_basics(
    payload: DatingBasics,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    existing_profile = get_user_profile(user.id)
    display_name = _clean_optional_text(
        payload.display_name or (existing_profile or {}).get("display_name") or user.display_name
    )
    city = _clean_optional_text(payload.city or (existing_profile or {}).get("city"))
    if not display_name:
        raise HTTPException(status_code=422, detail="Name is required.")
    if payload.age is None:
        raise HTTPException(status_code=422, detail="Age is required.")
    if not city:
        raise HTTPException(status_code=422, detail="Location is required.")
    profile = save_user_profile(
        user.id,
        payload.gender,
        payload.interested_in,
        display_name,
        payload.age,
        city,
        _clean_optional_text(payload.phone),
        (existing_profile or {}).get("profile_photo_url"),
        (existing_profile or {}).get("profile_photo_urls") or [],
        (existing_profile or {}).get("profile_photo_file_name"),
        (existing_profile or {}).get("profile_photo_file_names") or [],
    )
    return {"complete": True, "profile": profile}


@router.get("/api/me/profile")
async def get_me_profile(
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    profile = _profile_with_auth_defaults(get_user_profile(user.id), user)
    sources = _dedupe_context_sources(_reusable_context_sources(list_user_context_sources(user.id)))
    facts = list_profile_facts(user.id)
    data_point_feedback = list_data_point_feedback(user_id=user.id)
    data_point_feedback_by_fact = _latest_data_point_feedback_by_fact(data_point_feedback)
    facts_with_feedback = _profile_facts_with_feedback(facts, data_point_feedback_by_fact)
    response = {
        "user": _auth_user_payload(user),
        "profile": profile,
        "learned_facts": facts_with_feedback,
        "learned_fact_groups": _group_profile_facts(facts_with_feedback),
        "data_point_feedback_summary": _summarize_data_point_feedback(data_point_feedback),
        "profile_photo_max_count": PROFILE_PHOTO_MAX_COUNT,
        "style_sources": [
            _context_source_summary(source)
            for source in sources
            if source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
        ],
        "memory_sources": [
            _context_source_summary(source)
            for source in sources
            if source.get("source_type") not in STYLE_CONTEXT_SOURCE_TYPES
        ],
    }
    if _profile_debug_data_enabled():
        response["raw_internal_data_points"] = _raw_profile_data_points(
            facts_with_feedback,
            data_point_feedback_by_fact,
        )
    return response


@router.put("/api/me/profile")
async def put_me_profile(
    payload: UserProfilePatch,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    existing_profile = get_user_profile(user.id) or {}
    profile = save_user_profile(
        user.id,
        payload.gender,
        payload.interested_in,
        _clean_optional_text(payload.display_name),
        payload.age,
        _clean_optional_text(payload.city),
        _clean_optional_text(payload.phone),
        existing_profile.get("profile_photo_url"),
        existing_profile.get("profile_photo_urls") or [],
        existing_profile.get("profile_photo_file_name"),
        existing_profile.get("profile_photo_file_names") or [],
    )
    return {"profile": profile}


@router.get("/api/me/data-requests")
async def get_me_data_requests(
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return {"requests": list_user_data_requests(user.id)}


@router.post("/api/me/data-requests", status_code=201)
async def create_me_data_request(
    payload: DataRequestCreate,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    request = save_data_request(
        {
            "user_id": user.id,
            "email": user.email,
            "request_type": payload.request_type,
            "status": "open",
            "message": payload.message,
            "metadata": {
                "source": "account_profile",
                "display_name": user.display_name,
            },
        }
    )
    return {"request": request}


@router.delete("/api/me/account-data")
async def delete_me_account_data(
    confirm: bool = False,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    if not confirm:
        raise HTTPException(status_code=400, detail="Pass confirm=true to delete account data.")
    summary = delete_user_private_data(user.id, user.email)
    deleted_photos = _delete_profile_photo_file_names(summary.get("profile_photo_file_names", []))
    return {
        "user_id": user.id,
        "status": "deleted",
        "deleted": summary["deleted"],
        "deleted_profile_photos": deleted_photos,
    }


@router.post("/api/me/events", status_code=201)
async def create_me_app_events(
    payload: AppEventsBatchCreate,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    events = [
        {
            **event.model_dump(),
            "metadata": _safe_app_event_metadata(event.metadata),
        }
        for event in payload.events
    ]
    saved_events = save_app_events(user.id, events)
    return {"accepted": len(saved_events)}


def _safe_app_event_metadata(metadata: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key in _APP_EVENT_METADATA_ALLOWLIST:
        value = metadata.get(key)
        if isinstance(value, str):
            safe[key] = value[:160]
        elif isinstance(value, (bool, int, float)):
            safe[key] = value
    return safe


@router.post("/api/me/feedback", status_code=201)
async def create_me_feedback(
    payload: FeedbackSubmissionCreate,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    submission = save_feedback_submission(
        {
            "user_id": user.id,
            "email": user.email,
            "category": payload.category,
            "message": payload.message,
            "allow_contact": payload.allow_contact,
            "status": "open",
            "metadata": _safe_feedback_metadata(payload.metadata),
        }
    )
    return {"submission": submission}


@router.post("/api/me/community-invites", status_code=201)
async def create_me_community_invite(
    payload: CommunityInviteRequestCreate,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    message = payload.message or f"Please review me for a {payload.channel} community invite."
    submission = save_feedback_submission(
        {
            "user_id": user.id,
            "email": user.email,
            "category": "support",
            "message": message,
            "allow_contact": payload.allow_contact,
            "status": "open",
            "metadata": {
                **_safe_feedback_metadata(payload.metadata),
                "request_type": "community_invite",
                "channel": payload.channel,
            },
        }
    )
    return {"request": submission}


def _safe_feedback_metadata(metadata: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key in ("page", "source", "channel"):
        value = metadata.get(key)
        if isinstance(value, str):
            safe[key] = value[:160]
    return safe


@router.put("/api/me/profile-photo")
async def put_me_profile_photo(
    request: Request,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    extension = PROFILE_PHOTO_CONTENT_TYPES.get(content_type)
    if not extension:
        raise HTTPException(status_code=415, detail="Upload a JPG, PNG, WebP, or GIF image.")

    content = await request.body()
    if not content:
        raise HTTPException(status_code=400, detail="Profile photo is empty.")
    if len(content) > PROFILE_PHOTO_MAX_BYTES:
        max_mb = max(1, round(PROFILE_PHOTO_MAX_BYTES / (1024 * 1024)))
        raise HTTPException(status_code=413, detail=f"Profile photo must be {max_mb} MB or smaller.")

    existing_profile = get_user_profile(user.id)
    max_photo_count = PROFILE_PHOTO_MAX_COUNT
    existing_photo_urls = [
        str(url) if isinstance(url, str) else ""
        for url in ((existing_profile or {}).get("profile_photo_urls") or [])
    ][:max_photo_count]
    if not existing_photo_urls and (existing_profile or {}).get("profile_photo_url"):
        existing_photo_urls = [str((existing_profile or {}).get("profile_photo_url"))]
    existing_photo_file_names = [
        str(file_name) if isinstance(file_name, str) else ""
        for file_name in ((existing_profile or {}).get("profile_photo_file_names") or [])
    ][:max_photo_count]
    if not existing_photo_file_names and (existing_profile or {}).get("profile_photo_file_name"):
        existing_photo_file_names = [str((existing_profile or {}).get("profile_photo_file_name"))]
    raw_slot = request.query_params.get("slot")
    photo_slot: int | None = None
    if raw_slot not in (None, ""):
        try:
            photo_slot = int(raw_slot)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Profile photo slot must be between 0 and {max_photo_count - 1}.",
            ) from None
        if photo_slot < 0 or photo_slot >= max_photo_count:
            raise HTTPException(
                status_code=422,
                detail=f"Profile photo slot must be between 0 and {max_photo_count - 1}.",
            )
    active_photo_count = sum(1 for url in existing_photo_urls if url)
    if photo_slot is None and active_photo_count >= max_photo_count:
        raise HTTPException(
            status_code=422,
            detail=f"You can upload up to {max_photo_count} profile photo{'s' if max_photo_count != 1 else ''}.",
        )
    try:
        photo_url, photo_file_name = _store_profile_photo(
            user_id=user.id,
            content=content,
            content_type=content_type,
            extension=extension,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Profile photo upload failed for user %s", user.id)
        raise HTTPException(
            status_code=500,
            detail="Could not store profile photo. Check GCS bucket access or unset PROFILE_PHOTO_GCS_BUCKET locally.",
        ) from exc
    profile_photo_urls = existing_photo_urls[:max_photo_count]
    profile_photo_file_names = existing_photo_file_names[:max_photo_count]
    while len(profile_photo_urls) <= (photo_slot or -1):
        profile_photo_urls.append("")
    while len(profile_photo_file_names) < len(profile_photo_urls):
        profile_photo_file_names.append("")
    if photo_slot is not None and photo_slot < len(profile_photo_urls):
        profile_photo_urls[photo_slot] = photo_url
        profile_photo_file_names[photo_slot] = photo_file_name
    else:
        profile_photo_urls = [*profile_photo_urls, photo_url][:max_photo_count]
        profile_photo_file_names = [*profile_photo_file_names, photo_file_name][:max_photo_count]
    profile_photo_urls = profile_photo_urls[:max_photo_count]
    profile_photo_file_names = profile_photo_file_names[:max_photo_count]
    primary_photo_index = next((index for index, url in enumerate(profile_photo_urls) if url), 0)
    primary_photo_url = profile_photo_urls[primary_photo_index] or photo_url
    primary_photo_file_name = profile_photo_file_names[primary_photo_index] or photo_file_name
    if existing_profile:
        profile = save_user_profile(
            user.id,
            str(existing_profile.get("gender") or "prefer_not_to_say"),
            str(existing_profile.get("interested_in") or "everyone"),
            _clean_optional_text(existing_profile.get("display_name")),
            existing_profile.get("age"),
            _clean_optional_text(existing_profile.get("city")),
            _clean_optional_text(existing_profile.get("phone")),
            primary_photo_url,
            profile_photo_urls,
            primary_photo_file_name,
            profile_photo_file_names,
        )
    else:
        profile = save_user_profile(
            user.id,
            "prefer_not_to_say",
            "everyone",
            user.display_name,
            None,
            None,
            None,
            photo_url,
            [photo_url],
            photo_file_name,
            [photo_file_name],
        )
    return {
        "profile_photo_url": primary_photo_url,
        "profile_photo_urls": profile_photo_urls,
        "profile_photo_file_name": primary_photo_file_name,
        "profile_photo_file_names": profile_photo_file_names,
        "profile": profile,
    }


@router.delete("/api/me/profile-photo")
async def delete_me_profile_photo(
    request: Request,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    existing_profile = get_user_profile(user.id)
    if not existing_profile:
        raise HTTPException(status_code=404, detail="No profile photo found.")

    max_photo_count = PROFILE_PHOTO_MAX_COUNT
    raw_slot = request.query_params.get("slot", "0")
    try:
        photo_slot = int(raw_slot)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Profile photo slot must be between 0 and {max_photo_count - 1}.",
        ) from None
    if photo_slot < 0 or photo_slot >= max_photo_count:
        raise HTTPException(
            status_code=422,
            detail=f"Profile photo slot must be between 0 and {max_photo_count - 1}.",
        )

    profile_photo_urls = [
        str(url) if isinstance(url, str) else ""
        for url in (existing_profile.get("profile_photo_urls") or [])
    ][:max_photo_count]
    if not profile_photo_urls and existing_profile.get("profile_photo_url"):
        profile_photo_urls = [str(existing_profile.get("profile_photo_url"))]
    profile_photo_file_names = [
        str(file_name) if isinstance(file_name, str) else ""
        for file_name in (existing_profile.get("profile_photo_file_names") or [])
    ][:max_photo_count]
    if not profile_photo_file_names and existing_profile.get("profile_photo_file_name"):
        profile_photo_file_names = [str(existing_profile.get("profile_photo_file_name"))]

    while len(profile_photo_urls) <= photo_slot:
        profile_photo_urls.append("")
    while len(profile_photo_file_names) <= photo_slot:
        profile_photo_file_names.append("")
    removed_file_name = profile_photo_file_names[photo_slot]
    if not profile_photo_urls[photo_slot] and not removed_file_name:
        raise HTTPException(status_code=404, detail="No profile photo found in that slot.")

    profile_photo_urls[photo_slot] = ""
    profile_photo_file_names[photo_slot] = ""
    while profile_photo_urls and not profile_photo_urls[-1]:
        profile_photo_urls.pop()
    while profile_photo_file_names and len(profile_photo_file_names) > len(profile_photo_urls):
        profile_photo_file_names.pop()
    while len(profile_photo_file_names) < len(profile_photo_urls):
        profile_photo_file_names.append("")

    primary_photo_index = next((index for index, url in enumerate(profile_photo_urls) if url), None)
    primary_photo_url = profile_photo_urls[primary_photo_index] if primary_photo_index is not None else None
    primary_photo_file_name = (
        profile_photo_file_names[primary_photo_index] if primary_photo_index is not None else None
    )
    profile = save_user_profile(
        user.id,
        str(existing_profile.get("gender") or "prefer_not_to_say"),
        str(existing_profile.get("interested_in") or "everyone"),
        _clean_optional_text(existing_profile.get("display_name")),
        existing_profile.get("age"),
        _clean_optional_text(existing_profile.get("city")),
        _clean_optional_text(existing_profile.get("phone")),
        primary_photo_url,
        profile_photo_urls,
        primary_photo_file_name,
        profile_photo_file_names,
    )
    deleted_photo_files = _delete_profile_photo_file_names([removed_file_name])
    return {
        "profile_photo_url": primary_photo_url,
        "profile_photo_urls": profile_photo_urls,
        "profile_photo_file_name": primary_photo_file_name,
        "profile_photo_file_names": profile_photo_file_names,
        "deleted_profile_photos": deleted_photo_files,
        "profile": profile,
    }


@router.get("/api/me/profile-facts")
async def get_me_profile_facts(
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    facts = list_profile_facts(user.id)
    return {"facts": facts, "groups": _group_profile_facts(facts)}


@router.delete("/api/me/profile-facts/{fact_id}")
async def delete_me_profile_fact(
    fact_id: str,
    user: CurrentUser = Depends(require_user),
) -> dict[str, str]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    if not delete_profile_fact(fact_id, user.id):
        raise HTTPException(status_code=404, detail="Data point not found.")
    return {"fact_id": fact_id, "status": "deleted"}


@router.patch("/api/me/profile-facts/{fact_id}")
async def patch_me_profile_fact(
    fact_id: str,
    payload: ProfileFactPatch,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    fact = get_profile_fact(fact_id, user.id)
    if not fact:
        raise HTTPException(status_code=404, detail="Data point not found.")

    updated_fact = update_profile_fact_user_correction(
        fact_id,
        user.id,
        label=payload.label,
        status=payload.status,
    )
    if not updated_fact:
        raise HTTPException(status_code=404, detail="Data point not found.")

    feedback = normalize_data_point_feedback(
        {
            "user_id": user.id,
            "profile_fact_id": fact_id,
            "rating": "disagree" if payload.status == "rejected" else "agree",
            "reason": "user_corrected",
            "comment": payload.comment,
            "metadata": {
                "category": fact.get("category"),
                "key": fact.get("key"),
                "source_kind": fact.get("source_kind"),
                "source_id": fact.get("source_id"),
                "corrected_label": payload.label,
                "corrected_status": payload.status,
            },
        }
    )
    saved_feedback = save_data_point_feedback(feedback)
    return {
        "fact": {
            **updated_fact,
            "feedback": _data_point_feedback_summary_for_fact(saved_feedback),
        },
        "feedback": saved_feedback,
    }


@router.post("/api/me/profile-facts/{fact_id}/feedback")
async def create_data_point_feedback(
    fact_id: str,
    payload: DataPointFeedbackCreate,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    fact = get_profile_fact(fact_id, user.id)
    if not fact:
        raise HTTPException(status_code=404, detail="Data point not found.")

    feedback = normalize_data_point_feedback(
        {
            "user_id": user.id,
            "profile_fact_id": fact_id,
            "rating": payload.rating,
            "reason": payload.reason,
            "comment": payload.comment,
            "metadata": {
                "category": fact.get("category"),
                "key": fact.get("key"),
                "source_kind": fact.get("source_kind"),
                "source_id": fact.get("source_id"),
            },
        }
    )
    saved_feedback = save_data_point_feedback(feedback)
    updated_fact = get_profile_fact(fact_id, user.id)
    return {
        "feedback": saved_feedback,
        "fact": (
            {
                **updated_fact,
                "feedback": _data_point_feedback_summary_for_fact(saved_feedback),
            }
            if updated_fact
            else None
        ),
    }
