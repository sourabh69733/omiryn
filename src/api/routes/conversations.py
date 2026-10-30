from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query

from agent.feedback import normalize_message_feedback
from agent.cognition.background.idle import request_flush_now
from agent.feedback.rating_memory import sync_rating_memories
from agent.providers import AgentProviderError, agent_runtime_status, extract_profile
from security.auth import CurrentUser, require_user
from storage.audit_log import record_audit_event
from storage.conversations import is_temporary_conversation
from storage import (
    MessageDeletionError,
    count_memories_only_from_conversation,
    delete_conversation_messages,
    message_deletion_impact,
    threads_only_from_conversation,
    vibe_deletion_impact,
    delete_conversation as storage_delete_conversation,
    list_agent_message_feedback,
    list_context_sources,
    list_conversations as storage_list_conversations,
    list_user_context_sources,
    clear_agent_message_feedback,
    replace_agent_message_feedback,
    save_draft,
    set_conversation_archived,
)

from ..helpers import (
    _agent_persona_for_profile,
    _agent_user_context,
    _apply_dating_basics,
    _attached_context_sources,
    _get_existing_conversation,
    _normalize_agent_name,
    _normalize_selected_model,
    _profile_extraction_context_sources,
    _remember_user_timezone,
    _reusable_context_sources,
    _user_id,
    _validate_style_source,
)
from ..models import (
    AgentConversation,
    AgentConversationArchive,
    AgentConversationCreate,
    AgentConversationSettings,
    AgentConversationSummary,
    AgentMessageFeedbackCreate,
    AgentProfileSubmission,
    DraftProfile,
    MessageSelection,
    UserMessage,
)
from ..usage_limits import CHAT_MESSAGE_LIMIT, enforce_user_action_limit

from ..chat_service import (
    _change_messages,
    _find_message,
    _new_conversation,
    _reply_failed,
    _reply_to_pending,
    post_user_message,
)

router = APIRouter()


logger = logging.getLogger(__name__)


@router.post("/api/agent/conversations", status_code=201)
async def create_agent_conversation(
    payload: AgentConversationCreate | None = None,
    user: CurrentUser = Depends(require_user),
    timezone_header: str | None = Header(default=None, alias="X-Timezone"),
) -> AgentConversation:
    _remember_user_timezone(user, timezone_header)
    return _new_conversation(user, payload)

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
        if conversation.get("temporary") or conversation.get("import_source_id") or conversation.get("channel"):
            # A temporary chat lives only in the screen that opened it; a chat made from an
            # upload is only for Omi to learn from; a Telegram chat lives in Telegram. None
            # shows in History.
            continue
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
                archived_at=conversation.get("archived_at"),
            ).model_dump()
        )
    return {"count": len(summaries), "conversations": summaries}


@router.get("/api/agent/conversations/{conversation_id}")
async def get_agent_conversation(
    conversation_id: str,
    user: CurrentUser = Depends(require_user),
) -> AgentConversation:
    return _get_existing_conversation(conversation_id, user)


@router.get("/api/agent/conversations/{conversation_id}/messages")
async def list_agent_messages_after_sequence(
    conversation_id: str,
    after_sequence: int = Query(-1, ge=-1),
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    """Return the authoritative message tail used to repair realtime delivery gaps."""
    conversation = _get_existing_conversation(conversation_id, user)
    messages = [
        {"message_index": index, "message": message}
        for index, message in enumerate(conversation.messages)
        if index > after_sequence
    ]
    return {
        "conversation_id": conversation.id,
        "after_sequence": after_sequence,
        "latest_sequence": len(conversation.messages) - 1,
        "messages": messages,
    }


@router.post("/api/agent/conversations/{conversation_id}/messages/deletion-impact")
async def agent_messages_deletion_impact(
    conversation_id: str,
    payload: MessageSelection,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    """What deleting these messages also removes, shown before the user confirms."""
    _get_existing_conversation(conversation_id, user)
    try:
        return message_deletion_impact(_user_id(user), conversation_id, payload.message_indexes)
    except MessageDeletionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/agent/conversations/{conversation_id}/messages/delete")
async def delete_agent_messages(
    conversation_id: str,
    payload: MessageSelection,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    """Blank the chosen messages and forget what came only from them; the chat summary rebuilds."""
    _get_existing_conversation(conversation_id, user)
    try:
        result = delete_conversation_messages(_user_id(user), conversation_id, payload.message_indexes)
    except MessageDeletionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    record_audit_event(
        "messages.delete", actor_id=user.id, actor_role="user", target_user_id=user.id,
        target_id=conversation_id,
        detail={"message_count": result["message_count"], "memories_forgotten": result["memories_forgotten"]},
    )
    # Ratings on deleted replies went with them.
    _sync_rating_memories(_user_id(user))
    # Rebuild the chat summary, session log and topics from what is left.
    request_flush_now(conversation_id, _user_id(user))
    return result


@router.get("/api/agent/conversations/{conversation_id}/deletion-impact")
async def agent_conversation_deletion_impact(
    conversation_id: str,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    """What deleting this chat also removes, shown in the delete dialog before confirming."""
    _get_existing_conversation(conversation_id, user)
    owner_id = _user_id(user)
    vibe = vibe_deletion_impact(owner_id, conversation_id)
    return {
        "memories_forgotten": count_memories_only_from_conversation(owner_id, conversation_id),
        "vibe_removed": vibe["removed"],
        "vibe_weakened": vibe["weakened"],
        "topics_dropped": [
            thread["title"] for thread in threads_only_from_conversation(owner_id, conversation_id)
        ],
    }


@router.delete("/api/agent/conversations/{conversation_id}")
async def delete_agent_conversation(
    conversation_id: str,
    user: CurrentUser = Depends(require_user),
) -> dict[str, str]:
    # Deleting the conversation also deletes its pending jobs.
    temporary = is_temporary_conversation(conversation_id, _user_id(user))
    if not storage_delete_conversation(conversation_id, _user_id(user)):
        raise HTTPException(status_code=404, detail="Agent conversation not found.")
    record_audit_event(
        "chat.delete", actor_id=user.id, actor_role="user", target_user_id=user.id,
        target_id=conversation_id, detail={"temporary": temporary},
    )
    return {"conversation_id": conversation_id, "status": "deleted"}


@router.patch("/api/agent/conversations/{conversation_id}/archive")
def archive_agent_conversation(
    conversation_id: str,
    payload: AgentConversationArchive,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    """Archive or unarchive a chat. It keeps its messages; History lists it under Archived."""
    found, archived_at = set_conversation_archived(conversation_id, _user_id(user), payload.archived)
    if not found:
        raise HTTPException(status_code=404, detail="Agent conversation not found.")
    return {"conversation_id": conversation_id, "archived_at": archived_at}


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
    if payload.agent_voice is not None:
        conversation.agent_voice = payload.agent_voice
    if "agent_name" in payload.model_fields_set:
        conversation.agent_name = _normalize_agent_name(
            payload.agent_name,
            _agent_persona_for_profile(_agent_user_context(user)),
        )
    if "agent_style_source_id" in payload.model_fields_set:
        style_source_id = payload.agent_style_source_id or None
        _validate_style_source(conversation_id, style_source_id, _user_id(user))
        conversation.agent_style_source_id = style_source_id
    # Only the settings columns: a reply being written meanwhile keeps its messages.
    _change_messages(
        conversation,
        user,
        None,
        fields={
            field: getattr(conversation, field)
            for field in (
                "agent_provider", "agent_model", "agent_mode", "agent_tone",
                "agent_voice", "agent_name", "agent_style_source_id",
            )
        },
    )
    return conversation


@router.post("/api/agent/conversations/{conversation_id}/messages")
async def send_agent_message(
    conversation_id: str,
    payload: UserMessage,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_user),
    timezone_header: str | None = Header(default=None, alias="X-Timezone"),
) -> AgentConversation:
    conversation = _get_existing_conversation(conversation_id, user)
    _remember_user_timezone(user, timezone_header)
    return await post_user_message(
        conversation, user, payload.message, background_tasks, reply_to_index=payload.reply_to_index
    )

@router.post("/api/agent/conversations/{conversation_id}/messages/{message_index}/retry")
async def retry_agent_message(
    conversation_id: str,
    message_index: int,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_user),
    timezone_header: str | None = Header(default=None, alias="X-Timezone"),
) -> AgentConversation:
    """Reply again to the last message, whose earlier reply failed."""
    conversation = _get_existing_conversation(conversation_id, user)
    if conversation.status != "active":
        raise HTTPException(status_code=409, detail="Conversation already extracted.")
    messages = conversation.messages
    if (
        message_index != len(messages) - 1
        or messages[message_index].get("role") != "user"
        or not _reply_failed(messages[message_index])
    ):
        raise HTTPException(status_code=409, detail="This message has nothing to retry.")
    enforce_user_action_limit(_user_id(user), CHAT_MESSAGE_LIMIT)
    _remember_user_timezone(user, timezone_header)
    pending = dict(messages[message_index])

    def mark_sending(stored: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        index = _find_message(stored, message_index, pending)
        if index is None:
            return None
        stored[index]["delivery_status"] = "sending"
        return stored

    _change_messages(conversation, user, mark_sending)
    return await _reply_to_pending(
        conversation, user, conversation.messages[:message_index], pending, background_tasks
    )

def _sync_rating_memories(user_id: str) -> None:
    """A reason given on several bad replies becomes a lasting how-to-talk memory."""
    try:
        sync_rating_memories(user_id)
    except Exception:
        # The rating itself is saved; the lasting memory catches up on the next rating.
        logger.exception("agent.rating_memory.failed")

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
    if conversation.temporary:
        # Ratings teach Omi how to talk, and a temporary chat teaches nothing.
        raise HTTPException(status_code=400, detail="Temporary chats can't be rated.")

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
    saved = replace_agent_message_feedback(feedback)
    _sync_rating_memories(_user_id(user))
    return {"feedback": saved}


@router.delete("/api/agent/conversations/{conversation_id}/messages/{message_index}/feedback")
async def delete_agent_message_feedback(
    conversation_id: str,
    message_index: int,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    """Undo a rating; the next reply no longer learns from it."""
    _get_existing_conversation(conversation_id, user)
    cleared = clear_agent_message_feedback(_user_id(user), conversation_id, message_index)
    _sync_rating_memories(_user_id(user))
    return {"message_index": message_index, "cleared": cleared}


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
    if conversation.temporary:
        raise HTTPException(status_code=400, detail="Temporary chats are not used for your profile.")
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
    _change_messages(conversation, user, None, fields={"status": "extracted"})
    request_flush_now(conversation.id, _user_id(user))
    return {
        "draft_id": draft_id,
        "status": "draft",
        "review_url": f"/drafts/{draft_id}",
    }
