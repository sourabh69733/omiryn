from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from agent.memory_engine.data_point_extraction import (
    capture_hybrid_whatsapp_data_points,
    capture_llm_whatsapp_data_points,
    data_point_extractor_mode,
    should_run_hybrid_data_point_review,
    should_run_llm_data_point_extraction,
)
from agent.memory_engine.data_points import normalize_data_point
from agent.memory_engine.whatsapp_data_points import extract_whatsapp_data_points
from ingestion.whatsapp import build_whatsapp_structured_memory, build_whatsapp_style_summary
from security.auth import CurrentUser, require_user
from storage import (
    delete_context_source,
    delete_user_context_source,
    list_context_sources,
    list_user_context_sources,
    save_context_source,
    save_whatsapp_import_bundle,
    upsert_profile_fact,
)

from ..config import LLM_CONTEXT_IMPORT_PROMPT
from ..helpers import (
    _attached_context_source_by_original_id,
    _attached_context_source_ids,
    _attached_context_sources,
    _context_source_summary,
    _detect_conversation_tone,
    _get_existing_conversation,
    _reusable_context_sources,
    _user_id,
    _whatsapp_style_context_content,
)
from ..models import ContextSourceAttachmentsUpdate, ContextSourceCreate, WhatsappChatImportCreate
from ..usage_limits import CONTEXT_IMPORT_LIMIT, WHATSAPP_IMPORT_LIMIT, enforce_user_action_limit

router = APIRouter()


@router.get("/api/context-import-prompt")
def context_import_prompt() -> dict[str, str]:
    return {"prompt": LLM_CONTEXT_IMPORT_PROMPT}


@router.get("/api/agent/conversations/{conversation_id}/context-sources")
async def get_conversation_context_sources(
    conversation_id: str,
    user: CurrentUser = Depends(require_user),
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
    user: CurrentUser = Depends(require_user),
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
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    _get_existing_conversation(conversation_id, user)
    enforce_user_action_limit(_user_id(user), CONTEXT_IMPORT_LIMIT)
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
    user: CurrentUser = Depends(require_user),
) -> dict[str, str]:
    _get_existing_conversation(conversation_id, user)
    deleted = delete_user_context_source(source_id, user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Context source not found.")
    return {"source_id": source_id, "status": "deleted"}


@router.delete("/api/me/context-sources/{source_id}")
def delete_me_context_source(
    source_id: str,
    user: CurrentUser = Depends(require_user),
) -> dict[str, str]:
    if not delete_user_context_source(source_id, user.id):
        raise HTTPException(status_code=404, detail="Context source not found.")
    return {"source_id": source_id, "status": "deleted"}


@router.put("/api/agent/conversations/{conversation_id}/context-sources/attachments")
def update_conversation_context_attachments(
    conversation_id: str,
    payload: ContextSourceAttachmentsUpdate,
    user: CurrentUser = Depends(require_user),
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
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    _get_existing_conversation(conversation_id, user)
    enforce_user_action_limit(_user_id(user), WHATSAPP_IMPORT_LIMIT)
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
