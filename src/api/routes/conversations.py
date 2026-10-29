from __future__ import annotations

import logging
from dataclasses import dataclass
import sys
from collections.abc import Callable, Iterable
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query

from agent.feedback import normalize_message_feedback
from agent.memory_engine.engine import (
    capture_deep_profile_facts_from_conversation,
    should_run_conversation_data_point_extraction,
)
from agent.cognition.background.idle import request_flush_now, schedule_idle_flush
from agent.feedback.rating_memory import sync_rating_memories
from agent.providers.shared.model_catalog import preferred_reply_model
from agent.cognition.background.memory_run.service import (
    run_background_cognition,
    should_schedule_background_cognition,
    should_schedule_idle_background_cognition,
)
from agent.runtime.orchestrator import run_agent_turn
from agent.shared.clock import utc_now, utc_now_iso
from agent.shared.timeline import parse_time
from agent.providers import AgentProviderError, agent_runtime_status, extract_profile
from realtime import conversation_event, realtime_hub
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
    save_conversation,
    update_conversation,
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


def _change_messages(
    conversation: AgentConversation,
    user: CurrentUser,
    change: Callable[[list[dict[str, Any]]], list[dict[str, Any]] | None] | None,
    *,
    fields: dict[str, Any] | None = None,
) -> None:
    """Change the stored messages under the database lock and refresh `conversation` from what
    is stored now. A reply, a nudge or a second instance may have written meanwhile; the change
    works on the newest list, so no message is lost."""
    stored = update_conversation(conversation.id, _user_id(user), change, fields=fields)
    if stored is None:
        raise HTTPException(status_code=404, detail="Agent conversation not found.")
    conversation.messages = stored["messages"]
    for key, value in (fields or {}).items():
        setattr(conversation, key, value)


def _same_message(stored: dict[str, Any], sent: dict[str, Any]) -> bool:
    return (
        stored.get("role") == sent.get("role")
        and stored.get("created_at") == sent.get("created_at")
        and stored.get("content") == sent.get("content")
    )


def _find_message(messages: list[dict[str, Any]], index: int, sent: dict[str, Any]) -> int | None:
    """Where `sent` sits now: at its old index, unless messages were added or removed meanwhile."""
    if index < len(messages) and _same_message(messages[index], sent):
        return index
    for position in range(len(messages) - 1, -1, -1):
        if _same_message(messages[position], sent):
            return position
    return None


@router.post("/api/agent/conversations", status_code=201)
async def create_agent_conversation(
    payload: AgentConversationCreate | None = None,
    user: CurrentUser = Depends(require_user),
    timezone_header: str | None = Header(default=None, alias="X-Timezone"),
) -> AgentConversation:
    _remember_user_timezone(user, timezone_header)
    return _new_conversation(user, payload)


def channel_conversation(user: CurrentUser, channel: str) -> AgentConversation:
    """The user's ongoing chat on a messaging app, separate from the web chat; started if missing."""
    rows = [
        row
        for row in storage_list_conversations(_user_id(user))
        if row.get("channel") == channel and row.get("status") == "active"
    ]
    open_rows = [row for row in rows if not row.get("archived_at")]
    newest = max(open_rows or rows, key=lambda row: str(row.get("created_at") or ""), default=None)
    if newest is None:
        return _new_conversation(user, AgentConversationCreate(agent_tone="warm"), channel=channel)
    return AgentConversation.model_validate(newest)


def _new_conversation(
    user: CurrentUser, payload: AgentConversationCreate | None, channel: str | None = None
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
        temporary=bool(payload and payload.temporary),
        channel=channel,
        # A messaging app chat starts with the user's message; a greeting there was never sent.
        messages=[]
        if channel
        else [
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
    await _publish_messages(conversation, range(start_index, len(conversation.messages)))


async def _publish_messages(conversation: AgentConversation, indexes: Iterable[int]) -> None:
    for message_index in indexes:
        message = conversation.messages[message_index]
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


async def post_user_message(
    conversation: AgentConversation,
    user: CurrentUser,
    text: str,
    background_tasks: BackgroundTasks,
    *,
    reply_to_index: int | None = None,
    channel: str | None = None,
) -> AgentConversation:
    """Save the user's message, reply to it and schedule background learning.

    Shared by the web chat and messaging apps; `channel` marks where the message came from.
    """
    if conversation.status != "active":
        raise HTTPException(status_code=409, detail="Conversation already extracted.")
    if conversation.import_source_id:
        raise HTTPException(status_code=409, detail="This chat came from an upload; it can't be replied to.")
    enforce_user_action_limit(_user_id(user), CHAT_MESSAGE_LIMIT)
    pending = {
        "role": "user",
        "content": text,
        "created_at": utc_now_iso(),
        "delivery_status": "sending",
        **({"reply_to": _reply_quote(conversation.messages, reply_to_index)} if reply_to_index is not None else {}),
        **({"channel": channel} if channel else {}),
    }

    def add(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # A new message answers for any earlier one whose reply failed: the reply covers both.
        for message in messages:
            if message.get("role") == "user" and _reply_failed(message):
                message["delivery_status"] = "read"
        messages.append(dict(pending))
        return messages

    # Saved before the model runs, so a failed reply never loses what the user wrote.
    _change_messages(conversation, user, add)
    # Writing in an archived chat brings it back to the main list.
    set_conversation_archived(conversation.id, _user_id(user), False)
    return await _reply_to_pending(conversation, user, conversation.messages[:-1], pending, background_tasks)


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


# Enough of the quoted message to show in the bubble and tell Omi what is meant.
REPLY_QUOTE_CHARS = 300


def _sync_rating_memories(user_id: str) -> None:
    """A reason given on several bad replies becomes a lasting how-to-talk memory."""
    try:
        sync_rating_memories(user_id)
    except Exception:
        # The rating itself is saved; the lasting memory catches up on the next rating.
        logger.exception("agent.rating_memory.failed")


def _reply_quote(messages: list[dict[str, Any]], index: int) -> dict[str, Any]:
    if index >= len(messages):
        raise HTTPException(status_code=400, detail="The message you replied to was not found.")
    quoted = messages[index]
    text = " ".join(str(quoted.get("content") or "").replace("<next_message>", " ").split())
    if quoted.get("deleted") or not text or quoted.get("role") not in {"user", "assistant"}:
        raise HTTPException(status_code=400, detail="You can't reply to that message.")
    return {"index": index, "role": quoted["role"], "text": text[:REPLY_QUOTE_CHARS]}


async def _reply_to_pending(
    conversation: AgentConversation,
    user: CurrentUser,
    prior_messages: list[dict[str, Any]],
    pending: dict[str, Any],
    background_tasks: BackgroundTasks,
) -> AgentConversation:
    """Reply to `pending` (stored at index `len(prior_messages)` when this started) and save the
    reply after whatever the chat holds now: the user may have written again meanwhile."""
    pending_index = len(prior_messages)
    placed: dict[str, int | None] = {"user": None, "start": None}
    try:
        turn = await _run_turn(conversation, user, prior_messages, pending)
    except (AgentProviderError, Exception) as error:
        logger.warning(
            "agent.reply.failed conversation_id=%s error=%s", conversation.id, type(error).__name__
        )

        def mark_failed(stored: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
            placed["user"] = _find_message(stored, pending_index, pending)
            if placed["user"] is None:
                return None
            stored[placed["user"]]["delivery_status"] = REPLY_FAILED
            return stored

        _change_messages(conversation, user, mark_failed)
        raise HTTPException(
            status_code=502,
            detail={
                "code": REPLY_FAILED_CODE,
                "message": "Couldn't reply right now. Your message is saved; tap Retry.",
                "message_index": placed["user"] if placed["user"] is not None else pending_index,
            },
        ) from error

    answered = turn.messages[pending_index]
    replies = [dict(message) for message in turn.messages[pending_index + 1 :]]

    def commit(stored: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        # The stored message keeps when the user wrote it, the quote and the channel.
        placed["user"] = _find_message(stored, pending_index, pending)
        if placed["user"] is None:
            return None
        if answered.get("quality"):
            stored[placed["user"]]["quality"] = answered["quality"]
        stored[placed["user"]]["delivery_status"] = "read"
        placed["start"] = len(stored)
        stored.extend(replies)
        _stamp_new_messages(stored, placed["start"])
        return stored

    voice = getattr(turn, "agent_voice", None)
    _change_messages(conversation, user, commit, fields={"agent_voice": voice} if voice else None)
    if placed["user"] is None or placed["start"] is None:
        # The message was deleted while Omi wrote; the reply no longer fits the chat.
        logger.warning("agent.reply.dropped conversation_id=%s", conversation.id)
        return conversation
    await _publish_messages(
        conversation, [placed["user"], *range(placed["start"], len(conversation.messages))]
    )
    _learn_after_reply(conversation, user, turn.quality_valid, background_tasks)
    return conversation


async def _run_turn(
    conversation: AgentConversation,
    user: CurrentUser,
    prior_messages: list[dict[str, Any]],
    pending: dict[str, Any],
    unanswered_count: int = 1,
):
    """Omi's reply to `pending`, without saving it."""
    _sync_conversation_runtime(conversation, agent_runtime_status())
    return await _run_agent_turn_callable()(
        conversation_id=conversation.id,
        messages=prior_messages,
        user_text=str(pending["content"]),
        user_id=_user_id(user),
        user_profile=_agent_user_context(user),
        model=preferred_reply_model(_user_id(user), conversation.agent_model),
        agent_mode=conversation.agent_mode,
        agent_tone=conversation.agent_tone,
        agent_name=conversation.agent_name,
        style_source_id=conversation.agent_style_source_id,
        **({"reply_to": pending["reply_to"]} if pending.get("reply_to") else {}),
        **({"unanswered_count": unanswered_count} if unanswered_count > 1 else {}),
    )


def _learn_after_reply(
    conversation: AgentConversation,
    user: CurrentUser,
    quality_valid: bool,
    background_tasks: BackgroundTasks,
) -> None:
    """Schedule background learning from the chat after a saved reply."""
    if conversation.temporary:
        # Temporary Chat: no memories, vibe, notes, topics or profile facts from it.
        return
    if should_run_conversation_data_point_extraction(
        conversation.id,
        _user_id(user),
        conversation.messages,
        quality_valid,
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
        quality_valid,
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
        quality_valid,
    ):
        # Durable idle flush; after a threshold run it is a backstop that finds nothing
        # pending unless that run was lost to a crash or restart.
        # A how-to-talk request ("no questions", "chhota likho") is saved by this run too, in any
        # language, a couple of minutes after the chat goes quiet; the current chat follows it at once.
        schedule_idle_flush(conversation.id, _user_id(user))


# Messaging apps: a message is saved as it arrives and answered later, so several sent in a row
# can get one reply. Saving and committing never wait on anything in between, so in one process
# they never overwrite each other.


@dataclass(frozen=True)
class DraftReply:
    conversation_id: str
    # The last user message the draft answers; anything after it came in while writing.
    answered_through: int
    turn: Any


async def save_unanswered_message(user: CurrentUser, text: str, channel: str) -> AgentConversation:
    """Save a message in the user's chat on that app now; a later reply answers it."""
    conversation = channel_conversation(user, channel)
    if conversation.status != "active" or conversation.import_source_id:
        raise HTTPException(status_code=409, detail="This chat can't be replied to.")
    enforce_user_action_limit(_user_id(user), CHAT_MESSAGE_LIMIT)
    placed: dict[str, int] = {}

    def add(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        placed["index"] = len(messages)
        messages.append(
            {
                "role": "user",
                "content": text,
                "created_at": utc_now_iso(),
                "delivery_status": "sending",
                "channel": channel,
            }
        )
        return messages

    _change_messages(conversation, user, add)
    set_conversation_archived(conversation.id, _user_id(user), False)
    await _publish_new_messages(conversation, placed["index"])
    return conversation


async def draft_reply_to_unanswered(user: CurrentUser, conversation_id: str) -> DraftReply | None:
    """Omi's reply to every message since its last reply, read together. Nothing is saved."""
    conversation = _get_existing_conversation(conversation_id, user)
    unanswered = _unanswered_indexes(conversation.messages)
    if not unanswered:
        return None
    last = unanswered[-1]
    turn = await _run_turn(
        conversation,
        user,
        conversation.messages[:last],
        conversation.messages[last],
        unanswered_count=len(unanswered),
    )
    return DraftReply(conversation_id=conversation.id, answered_through=last, turn=turn)


async def commit_reply(
    user: CurrentUser, draft: DraftReply, background_tasks: BackgroundTasks
) -> list[dict[str, Any]]:
    """Save a draft's replies after the messages it answered; returns the reply messages."""
    conversation = _get_existing_conversation(draft.conversation_id, user)
    answered = draft.answered_through
    quality = draft.turn.messages[answered].get("quality")
    replies = [dict(message) for message in draft.turn.messages[answered + 1 :]]
    placed: dict[str, int | None] = {"first": None, "start": None}

    def commit(stored: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        if len(stored) <= answered or stored[answered].get("role") != "user":
            # Messages were deleted while Omi wrote; the reply no longer fits the chat.
            return None
        if quality:
            stored[answered]["quality"] = quality
        placed["first"] = _mark_answered(stored, answered)
        placed["start"] = len(stored)
        stored.extend(replies)
        _stamp_new_messages(stored, placed["start"])
        return stored

    voice = getattr(draft.turn, "agent_voice", None)
    _change_messages(conversation, user, commit, fields={"agent_voice": voice} if voice else None)
    if placed["first"] is None or placed["start"] is None:
        return []
    # From the first answered message, so the web chat also sees them marked read.
    await _publish_new_messages(conversation, placed["first"])
    _learn_after_reply(conversation, user, draft.turn.quality_valid, background_tasks)
    return conversation.messages[placed["start"] :]


def mark_unanswered_failed(user: CurrentUser, conversation_id: str) -> None:
    """The reply failed: the web chat shows these messages with a Retry."""
    conversation = _get_existing_conversation(conversation_id, user)

    def mark(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for index in _unanswered_indexes(messages):
            messages[index]["delivery_status"] = REPLY_FAILED
        return messages

    _change_messages(conversation, user, mark)


def _unanswered_indexes(messages: list[dict[str, Any]]) -> list[int]:
    """User messages after Omi's last message, oldest first."""
    indexes: list[int] = []
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("deleted"):
            continue
        if message.get("role") != "user":
            break
        indexes.append(index)
    return indexes[::-1]


def _mark_answered(messages: list[dict[str, Any]], through: int) -> int:
    """Mark the unanswered messages up to `through` read; returns the first one's index."""
    first = through
    for index in _unanswered_indexes(messages[: through + 1]):
        messages[index]["delivery_status"] = "read"
        first = min(first, index)
    return first


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
