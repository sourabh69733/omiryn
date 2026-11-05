"""Answers a burst of quick messages with one reply, on the web and on messaging apps.

A message is saved at once and counted into the chat's burst (`channel_bursts`), so several server
instances agree on it. The first one holds the replier lease and answers everything; the rest
return at once. Messages that arrive while Omi writes restart the draft, because nothing was
shown yet; after that they get the next reply.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any, AsyncContextManager, AsyncIterator, Awaitable, Callable

from fastapi import BackgroundTasks, HTTPException

from agent.providers import agent_runtime_status
from agent.shared.clock import utc_now
from realtime import conversation_event, realtime_hub
from security.auth import CurrentUser
from storage import burst_state, finish_burst, join_burst, release_burst, renew_burst, save_agent_trace_step

from .burst_window import DRAFT_HOLD_SECONDS, seconds_left, typing_active
from .chat_service import (
    REPLY_FAILED_CODE,
    WEB_CHANNEL,
    CommittedReply,
    _unanswered_indexes,
    commit_reply,
    draft_reply_to_unanswered,
    mark_retry_sending,
    mark_unanswered_failed,
    save_web_message,
)
from .helpers import _get_existing_conversation, _sync_conversation_runtime
from .models import AgentConversation

logger = logging.getLogger(__name__)

# Times a draft is thrown away because more messages came in before any of it was shown.
MAX_RESTARTS = 2
# A crashed replier's lease runs out and the next message's instance takes over, so a live
# replier renews it well before then, however long the model takes.
BURST_LEASE_SECONDS = 60.0
_LEASE_RENEW_SECONDS = 15.0
# While waiting for quiet, the burst row is re-read this often for messages that reached another instance.
_QUIET_POLL_SECONDS = 0.25


@dataclass(frozen=True)
class Burst:
    channel: str
    chat_id: str
    conversation_id: str
    token: str


@dataclass(frozen=True)
class BurstOutput:
    """How one kind of chat shows Omi at work."""

    writing: Callable[[], AsyncContextManager[None]]
    deliver: Callable[[CommittedReply], Awaitable[None]]


@dataclass
class _ReplyStats:
    """What the waiting did for one reply, kept in its trace to tune the window on real numbers."""

    waited_seconds: float = 0.0
    typing_held_seconds: float = 0.0
    # Came in while a typing signal was holding the reply: each would have cost a redraft or its own reply.
    messages_while_held: int = 0
    drafts_thrown_away: int = 0
    draft_held_seconds: float = 0.0


def join(channel: str, chat_id: str, conversation_id: str) -> Burst | None:
    """Count a saved message into the chat's burst; a Burst when this caller must answer it."""
    joined = join_burst(channel, chat_id, conversation_id, now=utc_now(), lease_seconds=BURST_LEASE_SECONDS)
    return Burst(channel, chat_id, conversation_id, joined["token"]) if joined["token"] else None


async def answer_burst(
    burst: Burst, user: CurrentUser, background_tasks: BackgroundTasks, output: BurstOutput
) -> None:
    """Reply until every counted message is answered. On failure the unanswered messages are marked
    for Retry and the error is raised."""
    lease = asyncio.create_task(_keep_lease(burst))
    try:
        await _reply_until_answered(burst, user, background_tasks, output)
    except Exception:
        _mark_failed(user, burst.conversation_id)
        raise
    finally:
        lease.cancel()
        with suppress(asyncio.CancelledError):
            await lease
        release_burst(burst.channel, burst.chat_id, burst.token)


async def _reply_until_answered(
    burst: Burst, user: CurrentUser, background_tasks: BackgroundTasks, output: BurstOutput
) -> None:
    answered = 0
    restarts = 0
    stats = _ReplyStats()
    while True:
        seen = await _wait_for_quiet(burst, answered, stats)
        if seen is None:
            return  # the lease was taken over
        async with output.writing():
            # The burst's first reply was counted when its first message was saved.
            draft = await draft_reply_to_unanswered(
                user, burst.conversation_id, count_quota=answered > 0 and restarts == 0
            )
            state = await _hold_for_typing(burst, seen, stats) if restarts < MAX_RESTARTS else _own_state(burst)
            if state is None:
                return
            if state["arrivals"] > seen and restarts < MAX_RESTARTS:
                # More came in while Omi wrote: start over so the reply covers those too.
                restarts += 1
                stats.drafts_thrown_away += 1
                continue
            committed = await commit_reply(user, draft, background_tasks) if draft else CommittedReply()
            _save_stats(user, burst, draft, stats)
        restarts = 0
        stats = _ReplyStats()
        await output.deliver(committed)
        answered = seen
        # Closes the burst only if nothing arrived since `seen`; otherwise go round again.
        if finish_burst(burst.channel, burst.chat_id, burst.token, answered=seen):
            return


def _own_state(burst: Burst) -> dict[str, Any] | None:
    state = burst_state(burst.channel, burst.chat_id)
    return state if state and state["token"] == burst.token else None


async def _wait_for_quiet(burst: Burst, answered: int, stats: _ReplyStats) -> int | None:
    """Wait for the chat to go quiet; returns how many messages the burst then holds."""
    started_at = utc_now()
    held_at_arrivals: int | None = None
    while True:
        state = _own_state(burst)
        if state is None:
            return None
        now = utc_now()
        if held_at_arrivals is not None:
            stats.messages_while_held += max(0, state["arrivals"] - held_at_arrivals)
        left = seconds_left(state["arrivals"] - answered, state["last_at"], started_at, now, state["typing_at"])
        if left <= 0:
            stats.waited_seconds += (now - started_at).total_seconds()
            return state["arrivals"]
        pause = min(left, _QUIET_POLL_SECONDS)
        held_at_arrivals = state["arrivals"] if typing_active(state["typing_at"], now) else None
        if held_at_arrivals is not None:
            stats.typing_held_seconds += pause
        await asyncio.sleep(pause)


async def _hold_for_typing(burst: Burst, seen: int, stats: _ReplyStats) -> dict[str, Any] | None:
    """The draft is done and nothing is shown yet. If they are typing right now, give that message a
    moment to land, so the reply does not arrive having missed it. Returns the burst's state."""
    started_at = utc_now()
    while True:
        state = _own_state(burst)
        if state is None:
            return None
        now = utc_now()
        held = (now - started_at).total_seconds()
        if state["arrivals"] > seen or not typing_active(state["typing_at"], now) or held >= DRAFT_HOLD_SECONDS:
            stats.draft_held_seconds += held
            return state
        await asyncio.sleep(_QUIET_POLL_SECONDS)


def _save_stats(user: CurrentUser, burst: Burst, draft: Any, stats: _ReplyStats) -> None:
    """Best effort: a reply is never lost over its numbers."""
    trace_id = getattr(getattr(draft, "turn", None), "trace_id", None)
    if not trace_id:
        return
    try:
        save_agent_trace_step(
            {
                "trace_id": trace_id,
                "user_id": user.id,
                "conversation_id": burst.conversation_id,
                "step_index": 5,
                "step_name": "burst_wait",
                "status": "ok",
                "metadata": {key: round(value, 2) for key, value in asdict(stats).items()},
            }
        )
    except Exception:
        logger.exception("burst.stats_failed")


async def _keep_lease(burst: Burst) -> None:
    while True:
        await asyncio.sleep(_LEASE_RENEW_SECONDS)
        until = utc_now() + timedelta(seconds=BURST_LEASE_SECONDS)
        if not renew_burst(burst.channel, burst.chat_id, burst.token, until=until):
            return


def _mark_failed(user: CurrentUser, conversation_id: str) -> None:
    try:
        mark_unanswered_failed(user, conversation_id)
    except Exception:
        logger.exception("burst.mark_failed.failed")


# The web chat: the first message's request stays open until the burst is answered (on Cloud Run it
# is what keeps CPU on) and returns the replies; the others return as soon as they are saved.


async def post_web_message(
    conversation: AgentConversation,
    user: CurrentUser,
    text: str,
    background_tasks: BackgroundTasks,
    *,
    reply_to_index: int | None = None,
    client_id: str | None = None,
) -> AgentConversation:
    await save_web_message(conversation, user, text, reply_to_index=reply_to_index, client_id=client_id)
    return await _answer_web(conversation, user, background_tasks)


async def retry_web_message(
    conversation: AgentConversation, user: CurrentUser, background_tasks: BackgroundTasks
) -> AgentConversation:
    mark_retry_sending(conversation, user)
    return await _answer_web(conversation, user, background_tasks)


async def _answer_web(
    conversation: AgentConversation, user: CurrentUser, background_tasks: BackgroundTasks
) -> AgentConversation:
    burst = join(WEB_CHANNEL, conversation.id, conversation.id)
    if burst is None:
        return conversation
    try:
        await answer_burst(burst, user, background_tasks, _web_output(conversation.id))
    except Exception as error:
        logger.warning("agent.reply.failed conversation_id=%s error=%s", conversation.id, type(error).__name__)
        stored = _get_existing_conversation(conversation.id, user)
        unanswered = _unanswered_indexes(stored.messages)
        raise HTTPException(
            status_code=502,
            detail={
                "code": REPLY_FAILED_CODE,
                "message": "Couldn't reply right now. Your message is saved; tap Retry.",
                "message_index": unanswered[-1] if unanswered else len(stored.messages) - 1,
            },
        ) from error
    answered = _get_existing_conversation(conversation.id, user)
    _sync_conversation_runtime(answered, agent_runtime_status())
    return answered


def _web_output(conversation_id: str) -> BurstOutput:
    @asynccontextmanager
    async def writing() -> AsyncIterator[None]:
        # Every tab of this chat shows the dots, not only the one whose request is open.
        await _publish_typing(conversation_id, True)
        try:
            yield
        finally:
            await _publish_typing(conversation_id, False)

    async def deliver(_committed: CommittedReply) -> None:
        return  # commit_reply already published them

    return BurstOutput(writing, deliver)


async def _publish_typing(conversation_id: str, active: bool) -> None:
    await realtime_hub.publish(
        conversation_event(
            "agent.typing",
            conversation_id,
            payload={"conversation_id": conversation_id, "active": active},
        )
    )
