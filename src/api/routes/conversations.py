from __future__ import annotations

import logging
import sys
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query

from agent.feedback import normalize_message_feedback
from agent.memory_engine.engine import (
    capture_deep_profile_facts_from_conversation,
    should_run_conversation_data_point_extraction,
)
from agent.cognition.background.idle import request_flush_now, schedule_idle_flush
from agent.cognition.background.service import (
    run_background_cognition,
    should_schedule_background_cognition,
    should_schedule_idle_background_cognition,
)
from agent.context_engine.conversation_engine.understanding.rules.stance import explicit_constraints
from agent.runtime.orchestrator import run_agent_turn
from agent.shared.clock import utc_now, utc_now_iso
from agent.shared.timeline import parse_time
from agent.providers import AgentProviderError, agent_runtime_status, extract_profile
from realtime import conversation_event, realtime_hub
from security.auth import CurrentUser, require_user
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
    save_agent_message_feedback,
    save_conversation,
    save_draft,
    set_conversation_archived,
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
    _remember_user_timezone,
    _reusable_context_sources,
    _sync_conversation_runtime,
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

router = APIRouter()


logger = logging.getLogger(__name__)
# A user message whose reply failed; it stays in the chat with a Retry.
REPLY_FAILED = "failed"
REPLY_FAILED_CODE = "reply_failed"


# A reply still "sending" after this long was lost (a crash or restart); treat it as failed.
_STALE_SENDING_SECONDS = 120


def _reply_failed(message: dict[str, Any]) -> bool:
    status = message.get("delivery_status")
    if status == REPLY_FAILED:
        return True
    sent = parse_time(message.get("created_at"))
    return status == "sending" and sent is not None and (
        utc_now() - sent
    ).total_seconds() > _STALE_SENDING_SECONDS


def _stamp_new_messages(messages: list[dict[str, object]], start_index: int = 0) -> None:
    timestamp = utc_now_iso()
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
    timezone_header: str | None = Header(default=None, alias="X-Timezone"),
) -> AgentConversation:
    _remember_user_timezone(user, timezone_header)
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
                "created_at": utc_now_iso(),
            }
        ],
    )
    save_conversation(conversation.model_dump(mode="json"), _user_id(user))
    return conversation


async def _publish_new_messages(
    conversation: AgentConversation,
    start_index: int,
) -> None:
    """Notify subscribed clients after durable message storage succeeds."""
    for message_index, message in enumerate(
        conversation.messages[start_index:],
        start=start_index,
    ):
        await realtime_hub.publish(
            conversation_event(
                "message.created",
                conversation.id,
                sequence=message_index,
                payload={
                    "conversation_id": conversation.id,
                    "message_index": message_index,
                    "message": {
                        "role": message.get("role"),
                        "content": message.get("content"),
                        "created_at": message.get("created_at"),
                        "delivery_status": message.get("delivery_status"),
                    },
                },
            )
        )


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
    if not storage_delete_conversation(conversation_id, _user_id(user)):
        raise HTTPException(status_code=404, detail="Agent conversation not found.")
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
    save_conversation(conversation.model_dump(mode="json"), _user_id(user))
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
    if conversation.status != "active":
        raise HTTPException(status_code=409, detail="Conversation already extracted.")
    enforce_user_action_limit(_user_id(user), CHAT_MESSAGE_LIMIT)
    _remember_user_timezone(user, timezone_header)
    # A new message answers for any earlier one whose reply failed: the reply covers both.
    for message in conversation.messages:
        if message.get("role") == "user" and _reply_failed(message):
            message["delivery_status"] = "read"
    prior_messages = list(conversation.messages)
    pending = {
        "role": "user",
        "content": payload.message,
        "created_at": utc_now_iso(),
        "delivery_status": "sending",
    }
    # Saved before the model runs, so a failed reply never loses what the user wrote.
    conversation.messages = [*prior_messages, pending]
    save_conversation(conversation.model_dump(mode="json"), _user_id(user))
    # Writing in an archived chat brings it back to the main list.
    set_conversation_archived(conversation_id, _user_id(user), False)
    return await _reply_to_pending(conversation, user, prior_messages, pending, background_tasks)


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
    pending = messages[message_index]
    pending["delivery_status"] = "sending"
    save_conversation(conversation.model_dump(mode="json"), _user_id(user))
    return await _reply_to_pending(
        conversation, user, messages[:message_index], pending, background_tasks
    )


async def _reply_to_pending(
    conversation: AgentConversation,
    user: CurrentUser,
    prior_messages: list[dict[str, Any]],
    pending: dict[str, Any],
    background_tasks: BackgroundTasks,
) -> AgentConversation:
    runtime = agent_runtime_status()
    _sync_conversation_runtime(conversation, runtime)
    try:
        turn = await _run_agent_turn_callable()(
            conversation_id=conversation.id,
            messages=prior_messages,
            user_text=str(pending["content"]),
            user_id=_user_id(user),
            user_profile=_agent_user_context(user),
            model=conversation.agent_model,
            agent_mode=conversation.agent_mode,
            agent_tone=conversation.agent_tone,
            agent_name=conversation.agent_name,
            style_source_id=conversation.agent_style_source_id,
        )
    except (AgentProviderError, Exception) as error:
        logger.warning(
            "agent.reply.failed conversation_id=%s error=%s", conversation.id, type(error).__name__
        )
        pending["delivery_status"] = REPLY_FAILED
        save_conversation(conversation.model_dump(mode="json"), _user_id(user))
        raise HTTPException(
            status_code=502,
            detail={
                "code": REPLY_FAILED_CODE,
                "message": "Couldn't reply right now. Your message is saved; tap Retry.",
                "message_index": len(prior_messages),
            },
        ) from error

    previous_message_count = len(prior_messages)
    conversation.messages = turn.messages
    if getattr(turn, "agent_voice", None):
        conversation.agent_voice = turn.agent_voice
    user_message = conversation.messages[previous_message_count]
    # Keep when the user actually wrote it, even when this reply came from a retry.
    user_message["created_at"] = pending["created_at"]
    user_message["delivery_status"] = "read"
    _stamp_new_messages(conversation.messages, previous_message_count)
    save_conversation(conversation.model_dump(mode="json"), _user_id(user))
    await _publish_new_messages(conversation, previous_message_count)
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
    run_cognition_now = should_schedule_background_cognition(
        conversation.id,
        _user_id(user),
        conversation.messages,
        turn.quality_valid,
    )
    if run_cognition_now:
        background_tasks.add_task(
            run_background_cognition,
            conversation.id,
            user.id,
            conversation.messages,
            conversation.agent_model,
        )
    if run_cognition_now or should_schedule_idle_background_cognition(
        conversation.id,
        _user_id(user),
        conversation.messages,
        turn.quality_valid,
    ):
        # Durable idle flush; after a threshold run it is a backstop that finds nothing
        # pending unless that run was lost to a crash or restart.
        schedule_idle_flush(conversation.id, _user_id(user))
        if not run_cognition_now and explicit_constraints(str(user_message.get("content") or "")):
            # "No questions", "just listen": save how they want to be talked to now, so their
            # other chats know it without waiting for the idle flush.
            request_flush_now(conversation.id, _user_id(user))
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
    request_flush_now(conversation.id, _user_id(user))
    return {
        "draft_id": draft_id,
        "status": "draft",
        "review_url": f"/drafts/{draft_id}",
    }
