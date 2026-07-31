from __future__ import annotations

import sys
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from agent.feedback import normalize_message_feedback
from agent.memory_engine.memory import (
    capture_deep_profile_facts_from_conversation,
    should_run_conversation_data_point_extraction,
)
from agent.runtime.orchestrator import run_agent_turn
from agent.runtime.providers import AgentProviderError, agent_runtime_status, extract_profile
from security.auth import CurrentUser, require_user
from storage import (
    delete_conversation as storage_delete_conversation,
    list_agent_message_feedback,
    list_context_sources,
    list_conversations as storage_list_conversations,
    list_user_context_sources,
    save_agent_message_feedback,
    save_conversation,
    save_draft,
)

from ..helpers import (
    _agent_persona_for_profile,
    _agent_user_context,
    _apply_dating_basics,
    _attached_context_sources,
    _get_existing_conversation,
    _initial_agent_message,
    _normalize_agent_name,
    _normalize_selected_model,
    _profile_extraction_context_sources,
    _reusable_context_sources,
    _sync_conversation_runtime,
    _user_id,
    _validate_style_source,
)
from ..models import (
    AgentConversation,
    AgentConversationCreate,
    AgentConversationSettings,
    AgentConversationSummary,
    AgentMessageFeedbackCreate,
    AgentProfileSubmission,
    DraftProfile,
    UserMessage,
)
from ..usage_limits import CHAT_MESSAGE_LIMIT, enforce_user_action_limit

router = APIRouter()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp_new_messages(messages: list[dict[str, object]], start_index: int = 0) -> None:
    timestamp = _utc_now_iso()
    for message in messages[start_index:]:
        message.setdefault("created_at", timestamp)
        if message.get("role") == "user":
            message.setdefault("delivery_status", "read")


def _run_agent_turn_callable():
    main_module = sys.modules.get("api.main")
    if main_module is None:
        return run_agent_turn
    return getattr(main_module, "run_agent_turn", run_agent_turn)


@router.post("/api/agent/conversations", status_code=201)
async def create_agent_conversation(
    payload: AgentConversationCreate | None = None,
    user: CurrentUser = Depends(require_user),
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
                "created_at": _utc_now_iso(),
            }
        ],
    )
    save_conversation(conversation.model_dump(mode="json"), _user_id(user))
    return conversation


@router.get("/api/agent/conversations")
async def list_agent_conversations(
    user: CurrentUser = Depends(require_user),
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
    user: CurrentUser = Depends(require_user),
) -> AgentConversation:
    return _get_existing_conversation(conversation_id, user)


@router.delete("/api/agent/conversations/{conversation_id}")
async def delete_agent_conversation(
    conversation_id: str,
    user: CurrentUser = Depends(require_user),
) -> dict[str, str]:
    if not storage_delete_conversation(conversation_id, _user_id(user)):
        raise HTTPException(status_code=404, detail="Agent conversation not found.")
    return {"conversation_id": conversation_id, "status": "deleted"}


@router.patch("/api/agent/conversations/{conversation_id}/settings")
def update_agent_conversation_settings(
    conversation_id: str,
    payload: AgentConversationSettings,
    user: CurrentUser = Depends(require_user),
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
    user: CurrentUser = Depends(require_user),
) -> AgentConversation:
    conversation = _get_existing_conversation(conversation_id, user)
    if conversation.status != "active":
        raise HTTPException(status_code=409, detail="Conversation already extracted.")
    enforce_user_action_limit(_user_id(user), CHAT_MESSAGE_LIMIT)
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

    previous_message_count = len(conversation.messages)
    conversation.messages = turn.messages
    _stamp_new_messages(conversation.messages, previous_message_count)
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
    user: CurrentUser = Depends(require_user),
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
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    _get_existing_conversation(conversation_id, user)
    feedback = list_agent_message_feedback(conversation_id, _user_id(user))
    return {"count": len(feedback), "feedback": feedback}


@router.post("/api/agent/conversations/{conversation_id}/extract")
async def extract_agent_conversation(
    conversation_id: str,
    user: CurrentUser = Depends(require_user),
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
