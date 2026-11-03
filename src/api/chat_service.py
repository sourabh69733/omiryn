"""The chat service behind the conversation routes and the messaging apps: how a user message is
saved, answered and learned from, and how messaging-app bursts are drafted and committed.

HTTP handling stays in `routes/conversations.py`; Telegram and WhatsApp call this module through
`routes/channel_replies.py`. Every message change goes through `_change_messages`, which works on
the newest stored list under the database lock.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
import sys
from collections.abc import Callable, Iterable
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, HTTPException

from agent.memory_engine.engine import (
    capture_deep_profile_facts_from_conversation,
    should_run_conversation_data_point_extraction,
)
from agent.cognition.background.idle import schedule_idle_flush
from agent.providers.shared.model_catalog import preferred_reply_model
from agent.cognition.background.memory_run.service import (
    run_background_cognition,
    should_schedule_background_cognition,
    should_schedule_idle_background_cognition,
)
from agent.runtime.orchestrator import run_agent_turn
from agent.shared.clock import utc_now, utc_now_iso
from agent.shared.timeline import parse_time
from agent.providers import agent_runtime_status
from realtime import conversation_event, realtime_hub
from security.auth import CurrentUser
from storage import (
    burst_open,
    list_conversations as storage_list_conversations,
    save_conversation,
    update_conversation,
    set_conversation_archived,
)

from .helpers import (
    _agent_persona_for_profile,
    _agent_user_context,
    _get_existing_conversation,
    _initial_agent_message,
    _normalize_agent_name,
    _normalize_selected_model,
    _sync_conversation_runtime,
    _user_id,
)
from .models import (
    AgentConversation,
    AgentConversationCreate,
)
from .usage_limits import CHAT_MESSAGE_LIMIT, enforce_quick_message_limit, enforce_user_action_limit


logger = logging.getLogger(__name__)
# The web chat's bursts are keyed by this and the conversation id, like a messaging app's chat.
WEB_CHANNEL = "web"
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
                        **({"client_id": message["client_id"]} if message.get("client_id") else {}),
                        **({"reply_to": message["reply_to"]} if message.get("reply_to") else {}),
                        **({"reaction": message["reaction"]} if message.get("reaction") else {}),
                    },
                },
            )
        )

async def save_web_message(
    conversation: AgentConversation,
    user: CurrentUser,
    text: str,
    *,
    reply_to_index: int | None = None,
    client_id: str | None = None,
) -> None:
    """Save the web chat's message now, before any model runs; a later reply answers it."""
    if conversation.status != "active":
        raise HTTPException(status_code=409, detail="Conversation already extracted.")
    if conversation.import_source_id:
        raise HTTPException(status_code=409, detail="This chat came from an upload; it can't be replied to.")
    _count_message(user, WEB_CHANNEL, conversation.id)
    pending = {
        "role": "user",
        "content": text,
        "created_at": utc_now_iso(),
        "delivery_status": "sending",
        **({"reply_to": _reply_quote(conversation.messages, reply_to_index)} if reply_to_index is not None else {}),
        **({"client_id": client_id} if client_id else {}),
    }
    placed: dict[str, int] = {}

    def add(messages: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        if client_id and any(message.get("client_id") == client_id for message in messages):
            return None  # the same send, retried after a lost connection
        # A new message answers for any earlier one whose reply failed: the reply covers both.
        for message in messages:
            if message.get("role") == "user" and _reply_failed(message):
                message["delivery_status"] = "read"
        placed["index"] = len(messages)
        messages.append(dict(pending))
        return messages

    _change_messages(conversation, user, add)
    # Writing in an archived chat brings it back to the main list.
    set_conversation_archived(conversation.id, _user_id(user), False)
    if "index" in placed:
        await _publish_new_messages(conversation, placed["index"])


def mark_retry_sending(conversation: AgentConversation, user: CurrentUser) -> None:
    """Retry answers every message whose reply failed, not only the last."""

    def mark(stored: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for index in _unanswered_indexes(stored):
            if _reply_failed(stored[index]):
                stored[index]["delivery_status"] = "sending"
        return stored

    _change_messages(conversation, user, mark)


def _count_message(user: CurrentUser, channel: str, chat_id: str) -> None:
    """A reply is what costs money, so the quota counts replies: a message that will share a reply
    already under way counts only against a high per-minute cap."""
    if burst_open(channel, chat_id, utc_now()):
        enforce_quick_message_limit(_user_id(user))
    else:
        enforce_user_action_limit(_user_id(user), CHAT_MESSAGE_LIMIT)


# Enough of the quoted message to show in the bubble and tell Omi what is meant.
REPLY_QUOTE_CHARS = 300

def _reply_quote(messages: list[dict[str, Any]], index: int) -> dict[str, Any]:
    if index >= len(messages):
        raise HTTPException(status_code=400, detail="The message you replied to was not found.")
    quoted = messages[index]
    text = " ".join(str(quoted.get("content") or "").replace("<next_message>", " ").split())
    if quoted.get("deleted") or not text or quoted.get("role") not in {"user", "assistant"}:
        raise HTTPException(status_code=400, detail="You can't reply to that message.")
    return {"index": index, "role": quoted["role"], "text": text[:REPLY_QUOTE_CHARS]}

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


# A message is saved as it arrives and answered later, so several sent in a row can get one reply
# (see reply_bursts.py). Saving and committing never wait on anything in between.


@dataclass(frozen=True)
class DraftReply:
    conversation_id: str
    # The last user message the draft answers; anything after it came in while writing.
    answered_through: int
    answered_message: dict[str, Any]
    turn: Any


async def save_unanswered_message(user: CurrentUser, text: str, channel: str, chat_id: str) -> AgentConversation:
    """Save a message in the user's chat on that app now; a later reply answers it."""
    conversation = channel_conversation(user, channel)
    if conversation.status != "active" or conversation.import_source_id:
        raise HTTPException(status_code=409, detail="This chat can't be replied to.")
    _count_message(user, channel, chat_id)
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


async def draft_reply_to_unanswered(
    user: CurrentUser, conversation_id: str, *, count_quota: bool = False
) -> DraftReply | None:
    """Omi's reply to every message since its last reply, read together. Nothing is saved."""
    conversation = _get_existing_conversation(conversation_id, user)
    unanswered = _unanswered_indexes(conversation.messages)
    if not unanswered:
        return None
    if count_quota:
        enforce_user_action_limit(_user_id(user), CHAT_MESSAGE_LIMIT)
    last = unanswered[-1]
    turn = await _run_turn(
        conversation,
        user,
        conversation.messages[:last],
        conversation.messages[last],
        unanswered_count=len(unanswered),
    )
    return DraftReply(
        conversation_id=conversation.id,
        answered_through=last,
        answered_message=dict(conversation.messages[last]),
        turn=turn,
    )


async def commit_reply(
    user: CurrentUser, draft: DraftReply, background_tasks: BackgroundTasks
) -> list[dict[str, Any]]:
    """Save a draft's replies right after the last message it answered; returns the reply messages.

    A message that came in later stays below them, so it still counts as unanswered and gets the
    next reply. Saved at the end, it would sit above a reply that never read it and never be answered.
    """
    conversation = _get_existing_conversation(draft.conversation_id, user)
    answered = draft.answered_through
    quality = draft.turn.messages[answered].get("quality")
    replies = [dict(message) for message in draft.turn.messages[answered + 1 :]]
    placed: dict[str, int | None] = {"first": None, "start": None}
    reaction = getattr(draft.turn, "reaction", None)
    no_reply = getattr(draft.turn, "no_reply", False)

    def commit(stored: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        index = _find_message(stored, answered, draft.answered_message)
        if index is None:
            # The message was deleted while Omi wrote; the reply no longer fits the chat.
            return None
        if quality:
            stored[index]["quality"] = quality
        placed["first"] = _mark_answered(stored, index)
        # After marking: a message with one of these no longer counts as unanswered.
        if reaction:
            stored[index]["reaction"] = reaction
        if no_reply:
            stored[index]["no_reply"] = True
        start = index + 1
        # Omi's own message that landed meanwhile (a nudge) stays above the reply.
        while start < len(stored) and stored[start].get("role") != "user":
            start += 1
        placed["start"] = start
        stored[start:start] = replies
        _stamp_new_messages(stored, start)
        return stored

    voice = getattr(draft.turn, "agent_voice", None)
    _change_messages(conversation, user, commit, fields={"agent_voice": voice} if voice else None)
    if placed["first"] is None or placed["start"] is None:
        return []
    # From the first answered message, so the web chat also sees them marked read.
    await _publish_new_messages(conversation, placed["first"])
    _learn_after_reply(conversation, user, draft.turn.quality_valid, background_tasks)
    return conversation.messages[placed["start"] : placed["start"] + len(replies)]


def mark_unanswered_failed(user: CurrentUser, conversation_id: str) -> None:
    """The reply failed: the web chat shows these messages with a Retry."""
    conversation = _get_existing_conversation(conversation_id, user)

    def mark(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for index in _unanswered_indexes(messages):
            messages[index]["delivery_status"] = REPLY_FAILED
        return messages

    _change_messages(conversation, user, mark)


def _unanswered_indexes(messages: list[dict[str, Any]]) -> list[int]:
    """User messages after Omi's last answer, oldest first. A reaction or a chosen silence is one."""
    indexes: list[int] = []
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("deleted"):
            continue
        if message.get("role") != "user" or message.get("reaction") or message.get("no_reply"):
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
