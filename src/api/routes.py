from __future__ import annotations

import sys
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from agent.feedback import normalize_message_feedback
from agent.memory_engine.data_point_feedback import normalize_data_point_feedback
from agent.memory_engine.data_point_extraction import (
    capture_hybrid_whatsapp_data_points,
    capture_llm_whatsapp_data_points,
    data_point_extractor_mode,
    should_run_hybrid_data_point_review,
    should_run_llm_data_point_extraction,
)
from agent.memory_engine.data_points import normalize_data_point
from agent.memory_engine.memory import (
    capture_deep_profile_facts_from_conversation,
    should_run_conversation_data_point_extraction,
)
from agent.memory_engine.whatsapp_data_points import extract_whatsapp_data_points
from agent.runtime.orchestrator import run_agent_turn
from agent.runtime.providers import AgentProviderError, agent_runtime_status, extract_profile
from agent.context_engine.context import STYLE_CONTEXT_SOURCE_TYPES
from ingestion.whatsapp import build_whatsapp_structured_memory, build_whatsapp_style_summary
from matching import AgePreference, Dealbreaker, MatchProfile, score_match
from security.auth import CurrentUser, current_user, public_auth_config
from storage import (
    delete_context_source,
    delete_user_context_source,
    delete_conversation as storage_delete_conversation,
    get_profile_fact,
    get_user_profile,
    list_context_sources,
    list_conversations as storage_list_conversations,
    list_profile_facts,
    list_data_point_feedback,
    list_user_context_sources,
    list_agent_trace_steps,
    list_agent_traces,
    list_agent_usage_events,
    list_agent_message_feedback,
    save_context_source,
    save_conversation,
    save_data_point_feedback,
    save_draft,
    save_agent_message_feedback,
    save_user_profile,
    save_whatsapp_import_bundle,
    summarize_agent_usage,
    upsert_profile_fact,
)

from .config import (
    APP_SHELL_HEADERS,
    LLM_CONTEXT_IMPORT_PROMPT,
    PROFILE_PHOTO_CONTENT_TYPES,
    PROFILE_PHOTO_MAX_BYTES,
    STATIC_DIR,
)
from .helpers import (
    _agent_persona_for_profile,
    _agent_user_context,
    _apply_dating_basics,
    _attached_context_source_by_original_id,
    _attached_context_source_ids,
    _attached_context_sources,
    _auth_user_payload,
    _basic_profile_complete,
    _clean_optional_text,
    _configured_usage_limits,
    _context_source_summary,
    _data_point_feedback_summary_for_fact,
    _dedupe_context_sources,
    _detect_conversation_tone,
    _get_existing_conversation,
    _get_existing_draft,
    _group_profile_facts,
    _initial_agent_message,
    _latest_data_point_feedback_by_fact,
    _normalize_agent_name,
    _normalize_selected_model,
    _profile_debug_data_enabled,
    _profile_extraction_context_sources,
    _profile_facts_with_feedback,
    _profile_with_auth_defaults,
    _raw_profile_data_points,
    _reusable_context_sources,
    _smart_reply_context_sources,
    _store_profile_photo,
    _summarize_data_point_feedback,
    _sync_conversation_runtime,
    _user_id,
    _validate_style_source,
    _whatsapp_style_context_content,
    logger,
)
from .models import (
    AgentConversation,
    AgentConversationCreate,
    AgentConversationSettings,
    AgentConversationSummary,
    AgentMessageFeedbackCreate,
    AgentProfileSubmission,
    ContextSourceAttachmentsUpdate,
    ContextSourceCreate,
    DataPointFeedbackCreate,
    DatingBasics,
    DraftPatch,
    DraftProfile,
    UserMessage,
    UserProfilePatch,
    WhatsappChatImportCreate,
)

router = APIRouter()


def _run_agent_turn_callable():
    main_module = sys.modules.get("api.main")
    if main_module is None:
        return run_agent_turn
    return getattr(main_module, "run_agent_turn", run_agent_turn)


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


@router.get("/api/me/dating-basics")
async def get_dating_basics(
    user: CurrentUser | None = Depends(current_user),
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
    user: CurrentUser | None = Depends(current_user),
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
    user: CurrentUser | None = Depends(current_user),
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
    user: CurrentUser | None = Depends(current_user),
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


@router.put("/api/me/profile-photo")
async def put_me_profile_photo(
    request: Request,
    user: CurrentUser | None = Depends(current_user),
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
    existing_photo_urls = [
        str(url) if isinstance(url, str) else ""
        for url in ((existing_profile or {}).get("profile_photo_urls") or [])
    ][:4]
    if not existing_photo_urls and (existing_profile or {}).get("profile_photo_url"):
        existing_photo_urls = [str((existing_profile or {}).get("profile_photo_url"))]
    existing_photo_file_names = [
        str(file_name) if isinstance(file_name, str) else ""
        for file_name in ((existing_profile or {}).get("profile_photo_file_names") or [])
    ][:4]
    if not existing_photo_file_names and (existing_profile or {}).get("profile_photo_file_name"):
        existing_photo_file_names = [str((existing_profile or {}).get("profile_photo_file_name"))]
    raw_slot = request.query_params.get("slot")
    photo_slot: int | None = None
    if raw_slot not in (None, ""):
        try:
            photo_slot = int(raw_slot)
        except ValueError:
            raise HTTPException(status_code=422, detail="Profile photo slot must be between 0 and 3.") from None
        if photo_slot < 0 or photo_slot > 3:
            raise HTTPException(status_code=422, detail="Profile photo slot must be between 0 and 3.")
    if photo_slot is None and len(existing_photo_urls) >= 4:
        raise HTTPException(status_code=422, detail="You can upload up to 4 profile photos.")

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
    profile_photo_urls = existing_photo_urls[:4]
    profile_photo_file_names = existing_photo_file_names[:4]
    while len(profile_photo_urls) <= (photo_slot or -1):
        profile_photo_urls.append("")
    while len(profile_photo_file_names) < len(profile_photo_urls):
        profile_photo_file_names.append("")
    if photo_slot is not None and photo_slot < len(profile_photo_urls):
        profile_photo_urls[photo_slot] = photo_url
        profile_photo_file_names[photo_slot] = photo_file_name
    else:
        profile_photo_urls = [*profile_photo_urls, photo_url][:4]
        profile_photo_file_names = [*profile_photo_file_names, photo_file_name][:4]
    profile_photo_urls = profile_photo_urls[:4]
    profile_photo_file_names = profile_photo_file_names[:4]
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


@router.get("/api/me/profile-facts")
async def get_me_profile_facts(
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    facts = list_profile_facts(user.id)
    return {"facts": facts, "groups": _group_profile_facts(facts)}


@router.post("/api/me/profile-facts/{fact_id}/feedback")
async def create_data_point_feedback(
    fact_id: str,
    payload: DataPointFeedbackCreate,
    user: CurrentUser | None = Depends(current_user),
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


@router.get("/api/agent/usage")
async def agent_usage(
    conversation_id: str | None = None,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    # Groq limits are API-key level, so the main dashboard should be app-wide.
    # Per-session usage remains scoped in /api/agent/conversations/{id}/usage.
    return {
        "summary": summarize_agent_usage(conversation_id, None),
        "events": list_agent_usage_events(conversation_id, None),
        "limits": _configured_usage_limits(),
    }


@router.get("/api/agent/conversations/{conversation_id}/usage")
async def conversation_agent_usage(
    conversation_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    _get_existing_conversation(conversation_id, user)
    return {
        "summary": summarize_agent_usage(conversation_id, _user_id(user)),
        "events": list_agent_usage_events(conversation_id, _user_id(user)),
        "limits": _configured_usage_limits(),
    }


@router.get("/api/agent/conversations/{conversation_id}/traces")
async def conversation_agent_traces(
    conversation_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    _get_existing_conversation(conversation_id, user)
    traces = list_agent_traces(conversation_id, _user_id(user))
    steps = list_agent_trace_steps(conversation_id=conversation_id, user_id=_user_id(user))
    steps_by_trace: dict[str, list[dict[str, object]]] = {}
    for step in steps:
        steps_by_trace.setdefault(str(step["trace_id"]), []).append(step)
    return {
        "count": len(traces),
        "traces": [
            {
                **trace,
                "steps": steps_by_trace.get(str(trace["id"]), []),
            }
            for trace in traces
        ],
    }


@router.get("/api/context-import-prompt")
def context_import_prompt() -> dict[str, str]:
    return {"prompt": LLM_CONTEXT_IMPORT_PROMPT}


@router.get("/api/agent/conversations/{conversation_id}/context-sources")
async def get_conversation_context_sources(
    conversation_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    _get_existing_conversation(conversation_id, user)
    sources = list_context_sources(conversation_id, _user_id(user))
    user_sources = _reusable_context_sources(list_user_context_sources(_user_id(user)))
    reusable_source_ids = {str(source["id"]) for source in user_sources}
    attached_sources = _attached_context_sources(sources, reusable_source_ids)
    attached_ids = _attached_context_source_ids(sources)
    return {
        "count": len(attached_sources),
        "sources": [
            _context_source_summary(source, attached=True)
            for source in attached_sources
        ],
        "available_sources": [
            _context_source_summary(source, attached=source["id"] in attached_ids)
            for source in user_sources
        ],
    }


@router.get("/api/agent/conversations/{conversation_id}/tone")
async def get_conversation_tone(
    conversation_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    conversation = _get_existing_conversation(conversation_id, user)
    return {
        "selected_tone": conversation.agent_tone,
        "detected_tone": _detect_conversation_tone(
            conversation.messages,
            list_context_sources(conversation_id, _user_id(user)),
        ),
    }


@router.post("/api/agent/conversations/{conversation_id}/context-sources", status_code=201)
def create_conversation_context_source(
    conversation_id: str,
    payload: ContextSourceCreate,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    _get_existing_conversation(conversation_id, user)
    source = save_context_source(
        {
            "user_id": _user_id(user),
            "conversation_id": conversation_id,
            "source_type": payload.source_type,
            "title": payload.title,
            "content": payload.content,
            "metadata": {"content_length": len(payload.content)},
        }
    )
    return _context_source_summary(source)


@router.delete("/api/agent/conversations/{conversation_id}/context-sources/{source_id}")
def delete_conversation_context_source(
    conversation_id: str,
    source_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, str]:
    _get_existing_conversation(conversation_id, user)
    deleted = (
        delete_user_context_source(source_id, user.id)
        if user
        else delete_context_source(source_id, conversation_id, None)
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Context source not found.")
    return {"source_id": source_id, "status": "deleted"}


@router.delete("/api/me/context-sources/{source_id}")
def delete_me_context_source(
    source_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, str]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    if not delete_user_context_source(source_id, user.id):
        raise HTTPException(status_code=404, detail="Context source not found.")
    return {"source_id": source_id, "status": "deleted"}


@router.put("/api/agent/conversations/{conversation_id}/context-sources/attachments")
def update_conversation_context_attachments(
    conversation_id: str,
    payload: ContextSourceAttachmentsUpdate,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    _get_existing_conversation(conversation_id, user)
    user_id = _user_id(user)
    requested_ids = list(dict.fromkeys(payload.source_ids))
    reusable_sources = _reusable_context_sources(list_user_context_sources(user_id))
    reusable_by_id = {str(source["id"]): source for source in reusable_sources}
    unknown_ids = [source_id for source_id in requested_ids if source_id not in reusable_by_id]
    if unknown_ids:
        raise HTTPException(status_code=404, detail="One or more saved context items were not found.")

    attached_sources = list_context_sources(conversation_id, user_id)
    for source_id in requested_ids:
        source = reusable_by_id[source_id]
        if _attached_context_source_by_original_id(attached_sources, source_id):
            continue
        save_context_source(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "source_type": source["source_type"],
                "title": source["title"],
                "content": source["content"],
                "metadata": {
                    **(source.get("metadata") or {}),
                    "original_source_id": source["id"],
                    "attached_from_conversation_id": source["conversation_id"],
                },
            }
        )

    for source in attached_sources:
        metadata = source.get("metadata") or {}
        original_source_id = metadata.get("original_source_id") if isinstance(metadata, dict) else None
        if original_source_id and original_source_id not in requested_ids:
            delete_context_source(str(source["id"]), conversation_id, user_id)

    sources = list_context_sources(conversation_id, user_id)
    user_sources = _reusable_context_sources(list_user_context_sources(user_id))
    reusable_source_ids = {str(source["id"]) for source in user_sources}
    attached_sources = _attached_context_sources(sources, reusable_source_ids)
    attached_ids = _attached_context_source_ids(sources)
    return {
        "count": len(attached_sources),
        "sources": [
            _context_source_summary(source, attached=True)
            for source in attached_sources
        ],
        "available_sources": [
            _context_source_summary(source, attached=source["id"] in attached_ids)
            for source in user_sources
        ],
    }


@router.post("/api/agent/conversations/{conversation_id}/whatsapp-import", status_code=201)
def create_whatsapp_context_source(
    conversation_id: str,
    payload: WhatsappChatImportCreate,
    background_tasks: BackgroundTasks,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    _get_existing_conversation(conversation_id, user)
    try:
        style_summary = build_whatsapp_style_summary(
            payload.content,
            user_sender=payload.user_sender,
        )
        structured_memory = build_whatsapp_structured_memory(
            payload.content,
            user_sender=payload.user_sender,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    source = save_context_source(
        {
            "user_id": _user_id(user),
            "conversation_id": conversation_id,
            "source_type": "friend_style"
            if payload.style_kind == "friend_style"
            else "whatsapp_chat",
            "title": payload.title,
            "content": _whatsapp_style_context_content(
                style_summary.content,
                payload.style_kind,
                payload.style_name or payload.title,
            ),
            "metadata": {
                **style_summary.metadata,
                "style_kind": payload.style_kind,
                "style_name": payload.style_name,
            },
        }
    )
    whatsapp_import = save_whatsapp_import_bundle(
        {
            "user_id": _user_id(user),
            "conversation_id": conversation_id,
            "context_source_id": source["id"],
            "style_kind": payload.style_kind,
            "title": payload.title,
            "selected_sender": structured_memory.metadata.get("selected_sender"),
            "metadata": {
                **structured_memory.metadata,
                "style_name": payload.style_name,
            },
            "messages": [
                {
                    "message_index": index,
                    "sender": message.sender,
                    "timestamp_text": message.timestamp_text,
                    "content": message.content,
                }
                for index, message in enumerate(structured_memory.messages)
            ],
            "chunks": [
                {
                    "chunk_index": chunk.chunk_index,
                    "start_message_index": chunk.start_message_index,
                    "end_message_index": chunk.end_message_index,
                    "content": chunk.content,
                    "terms": chunk.terms,
                    "embedding": chunk.embedding,
                    "metadata": chunk.metadata,
                }
                for chunk in structured_memory.chunks
            ],
            "people": [
                {
                    "sender": person.sender,
                    "message_count": person.message_count,
                    "role": person.role,
                    "metadata": person.metadata,
                }
                for person in structured_memory.people
            ],
            "style_profiles": [
                {
                    "sender": profile.sender,
                    "summary": profile.summary,
                    "sample_messages": profile.sample_messages,
                    "metadata": profile.metadata,
                }
                for profile in structured_memory.style_profiles
            ],
        },
        _user_id(user),
    )
    extractor_mode = data_point_extractor_mode()
    if user and extractor_mode == "rules":
        for point in extract_whatsapp_data_points(
            structured_memory,
            user_id=user.id,
            source_id=source["id"],
            import_id=str(whatsapp_import["id"]),
            title=payload.title,
        ):
            upsert_profile_fact(normalize_data_point(point))
    if user and should_run_llm_data_point_extraction():
        background_tasks.add_task(
            capture_llm_whatsapp_data_points,
            structured_memory,
            user_id=user.id,
            source_id=source["id"],
            import_id=str(whatsapp_import["id"]),
            title=payload.title,
            conversation_id=conversation_id,
        )
    if user and should_run_hybrid_data_point_review():
        background_tasks.add_task(
            capture_hybrid_whatsapp_data_points,
            structured_memory,
            user_id=user.id,
            source_id=source["id"],
            import_id=str(whatsapp_import["id"]),
            title=payload.title,
            conversation_id=conversation_id,
        )
    return _context_source_summary(source)


@router.get("/")
def root(request: Request) -> FileResponse:
    host = request.headers.get("host", "").split(":", 1)[0].lower()
    if host.startswith("app."):
        return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)
    return FileResponse(STATIC_DIR / "landing.html", headers=APP_SHELL_HEADERS)


@router.get("/app")
def app_shell() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)


@router.post("/api/agent/conversations", status_code=201)
async def create_agent_conversation(
    payload: AgentConversationCreate | None = None,
    user: CurrentUser | None = Depends(current_user),
) -> AgentConversation:
    conversation_id = str(uuid4())
    runtime = agent_runtime_status()
    selected_model = _normalize_selected_model(
        payload.agent_model if payload else None,
        runtime,
    )
    user_profile = _agent_user_context(user)
    persona = _agent_persona_for_profile(user_profile)
    agent_name = _normalize_agent_name(payload.agent_name if payload else None, persona)
    conversation = AgentConversation(
        id=conversation_id,
        agent_provider=str(runtime["provider"]),
        agent_model=selected_model,
        agent_mode=payload.agent_mode if payload else "know_me",
        agent_tone=payload.agent_tone if payload else "auto",
        agent_name=agent_name,
        agent_style_source_id=payload.agent_style_source_id if payload else None,
        messages=[
            {
                "role": "assistant",
                "content": _initial_agent_message({**persona, "name": agent_name}, user_profile),
            }
        ],
    )
    save_conversation(conversation.model_dump(mode="json"), _user_id(user))
    return conversation


@router.get("/api/agent/conversations")
async def list_agent_conversations(
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    conversations = storage_list_conversations(_user_id(user))
    summaries = []
    reusable_source_ids = {
        str(source["id"])
        for source in _reusable_context_sources(list_user_context_sources(_user_id(user)))
    }
    for conversation in conversations:
        messages = conversation["messages"]
        context_sources = list_context_sources(conversation["id"], _user_id(user))
        summaries.append(
            AgentConversationSummary(
                id=conversation["id"],
                status=conversation["status"],
                agent_provider=conversation["agent_provider"],
                agent_model=conversation["agent_model"],
                agent_mode=conversation["agent_mode"],
                agent_tone=conversation["agent_tone"],
                agent_name=conversation.get("agent_name")
                or _agent_persona_for_profile(_agent_user_context(user))["name"],
                agent_style_source_id=conversation["agent_style_source_id"],
                message_count=len(messages),
                user_message_count=sum(1 for message in messages if message.get("role") == "user"),
                context_source_count=len(_attached_context_sources(context_sources, reusable_source_ids)),
                created_at=conversation["created_at"],
                updated_at=conversation["updated_at"],
            ).model_dump()
        )
    return {"count": len(summaries), "conversations": summaries}


@router.get("/api/agent/conversations/{conversation_id}")
async def get_agent_conversation(
    conversation_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> AgentConversation:
    return _get_existing_conversation(conversation_id, user)


@router.delete("/api/agent/conversations/{conversation_id}")
async def delete_agent_conversation(
    conversation_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, str]:
    if not storage_delete_conversation(conversation_id, _user_id(user)):
        raise HTTPException(status_code=404, detail="Agent conversation not found.")
    return {"conversation_id": conversation_id, "status": "deleted"}


@router.patch("/api/agent/conversations/{conversation_id}/settings")
def update_agent_conversation_settings(
    conversation_id: str,
    payload: AgentConversationSettings,
    user: CurrentUser | None = Depends(current_user),
) -> AgentConversation:
    conversation = _get_existing_conversation(conversation_id, user)
    if conversation.status != "active":
        raise HTTPException(status_code=409, detail="Conversation already extracted.")

    runtime = agent_runtime_status()
    conversation.agent_provider = str(runtime["provider"])
    if payload.agent_model is not None:
        conversation.agent_model = _normalize_selected_model(payload.agent_model, runtime)
    if payload.agent_mode is not None:
        conversation.agent_mode = payload.agent_mode
    if payload.agent_tone is not None:
        conversation.agent_tone = payload.agent_tone
    if "agent_name" in payload.model_fields_set:
        conversation.agent_name = _normalize_agent_name(
            payload.agent_name,
            _agent_persona_for_profile(_agent_user_context(user)),
        )
    if "agent_style_source_id" in payload.model_fields_set:
        style_source_id = payload.agent_style_source_id or None
        _validate_style_source(conversation_id, style_source_id, _user_id(user))
        conversation.agent_style_source_id = style_source_id
    save_conversation(conversation.model_dump(mode="json"), _user_id(user))
    return conversation


@router.post("/api/agent/conversations/{conversation_id}/messages")
async def send_agent_message(
    conversation_id: str,
    payload: UserMessage,
    background_tasks: BackgroundTasks,
    user: CurrentUser | None = Depends(current_user),
) -> AgentConversation:
    conversation = _get_existing_conversation(conversation_id, user)
    if conversation.status != "active":
        raise HTTPException(status_code=409, detail="Conversation already extracted.")
    runtime = agent_runtime_status()
    _sync_conversation_runtime(conversation, runtime)

    try:
        turn = await _run_agent_turn_callable()(
            conversation_id=conversation.id,
            messages=conversation.messages,
            user_text=payload.message,
            user_id=_user_id(user),
            user_profile=_agent_user_context(user),
            model=conversation.agent_model,
            agent_mode=conversation.agent_mode,
            agent_tone=conversation.agent_tone,
            agent_name=conversation.agent_name,
            style_source_id=conversation.agent_style_source_id,
        )
    except (AgentProviderError, Exception) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    conversation.messages = turn.messages
    save_conversation(conversation.model_dump(mode="json"), _user_id(user))
    if should_run_conversation_data_point_extraction(
        conversation.id,
        _user_id(user),
        conversation.messages,
        turn.quality_valid,
    ):
        background_tasks.add_task(
            capture_deep_profile_facts_from_conversation,
            conversation.id,
            user.id,
            conversation.messages,
            conversation.agent_model,
        )
    return conversation


@router.post("/api/agent/conversations/{conversation_id}/messages/{message_index}/feedback")
async def create_agent_message_feedback(
    conversation_id: str,
    message_index: int,
    payload: AgentMessageFeedbackCreate,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    conversation = _get_existing_conversation(conversation_id, user)
    if message_index < 0 or message_index >= len(conversation.messages):
        raise HTTPException(status_code=404, detail="Conversation message not found.")
    if conversation.messages[message_index].get("role") != "assistant":
        raise HTTPException(status_code=400, detail="Feedback can only be added to agent messages.")

    feedback = normalize_message_feedback(
        {
            "conversation_id": conversation_id,
            "user_id": _user_id(user),
            "message_index": message_index,
            "rating": payload.rating,
            "reason": payload.reason,
            "comment": payload.comment,
            "metadata": {
                "agent_provider": conversation.agent_provider,
                "agent_model": conversation.agent_model,
                "agent_name": conversation.agent_name,
                "reasons": payload.reasons,
            },
        }
    )
    return {"feedback": save_agent_message_feedback(feedback)}


@router.get("/api/agent/conversations/{conversation_id}/feedback")
async def get_agent_message_feedback(
    conversation_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    _get_existing_conversation(conversation_id, user)
    feedback = list_agent_message_feedback(conversation_id, _user_id(user))
    return {"count": len(feedback), "feedback": feedback}


@router.post("/api/agent/conversations/{conversation_id}/extract")
async def extract_agent_conversation(
    conversation_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, str]:
    conversation = _get_existing_conversation(conversation_id, user)
    try:
        raw_profile = await extract_profile(
            conversation.messages,
            conversation_id=conversation.id,
            model=conversation.agent_model,
            context_sources=_profile_extraction_context_sources(conversation.id, _user_id(user)),
        )
        submission = AgentProfileSubmission.model_validate(raw_profile)
        _apply_dating_basics(submission, user)
    except (AgentProviderError, ValueError, TypeError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    draft_id = str(uuid4())
    save_draft(
        DraftProfile(id=draft_id, status="draft", submission=submission).model_dump(mode="json"),
        _user_id(user),
    )
    conversation.status = "extracted"
    save_conversation(conversation.model_dump(mode="json"), _user_id(user))
    return {
        "draft_id": draft_id,
        "status": "draft",
        "review_url": f"/drafts/{draft_id}",
    }


@router.post("/api/agent-submissions/profile", status_code=201)
async def submit_agent_profile(
    submission: AgentProfileSubmission,
    user: CurrentUser | None = Depends(current_user),
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
    user: CurrentUser | None = Depends(current_user),
) -> DraftProfile:
    return _get_existing_draft(draft_id, user)


@router.patch("/api/drafts/{draft_id}")
async def update_draft(
    draft_id: str,
    patch: DraftPatch,
    user: CurrentUser | None = Depends(current_user),
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
    user: CurrentUser | None = Depends(current_user),
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
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, str]:
    draft = _get_existing_draft(draft_id, user)
    save_draft(
        DraftProfile(id=draft.id, status="deleted", submission=draft.submission).model_dump(
            mode="json"
        ),
        _user_id(user),
    )
    return {"draft_id": draft_id, "status": "deleted"}


@router.get("/drafts/{draft_id}")
def draft_review_page(draft_id: str) -> FileResponse:
    _get_existing_draft(draft_id)
    return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)


@router.get("/matches")
def matches_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)


@router.get("/style")
def style_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)


@router.get("/profile")
def profile_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)


@router.get("/usage")
def usage_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)


@router.get("/api/demo/matches")
async def demo_matches(user: CurrentUser | None = Depends(current_user)) -> dict[str, object]:
    user = MatchProfile(
        id="user-demo",
        age=29,
        age_preference=AgePreference(min=26, max=33),
        relationship_intent="long_term",
        values=["family", "ambition", "emotional_stability"],
        lifestyle=["fitness", "travel", "balanced_work"],
        communication_style="direct",
        religion_importance="medium",
        family_involvement="medium",
        children_preference="wants_children",
        city="Bengaluru",
        dealbreakers=[Dealbreaker(type="smoking", severity="hard")],
        attributes=["vegetarian", "non_smoker"],
    )
    candidates = [
        MatchProfile(
            id="match-1",
            age=28,
            age_preference=AgePreference(min=28, max=34),
            relationship_intent="marriage",
            values=["family", "ambition", "kindness"],
            lifestyle=["fitness", "travel", "early_riser"],
            communication_style="direct",
            religion_importance="medium",
            family_involvement="medium",
            children_preference="wants_children",
            city="Bengaluru",
            dealbreakers=[Dealbreaker(type="heavy_drinking", severity="hard")],
            attributes=["non_smoker"],
        ),
        MatchProfile(
            id="match-2",
            age=31,
            age_preference=AgePreference(min=27, max=35),
            relationship_intent="long_term",
            values=["curiosity", "family", "calm"],
            lifestyle=["travel", "balanced_work", "reading"],
            communication_style="reflective",
            religion_importance="low",
            family_involvement="medium",
            children_preference="open",
            city="Mumbai",
            open_to_relocation=True,
            dealbreakers=[],
            attributes=["non_smoker"],
        ),
        MatchProfile(
            id="match-3",
            age=27,
            age_preference=AgePreference(min=29, max=36),
            relationship_intent="casual",
            values=["adventure", "independence"],
            lifestyle=["nightlife"],
            communication_style="spontaneous",
            city="Bengaluru",
            attributes=["smoking"],
        ),
    ]

    names = {
        "match-1": "Meera",
        "match-2": "Isha",
        "match-3": "Rhea",
    }

    return {
        "matches": [
            {
                "id": candidate.id,
                "name": names[candidate.id],
                "age": candidate.age,
                "city": candidate.city,
                "result": score_match(user, candidate),
            }
            for candidate in candidates
        ]
    }
