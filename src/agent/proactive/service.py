"""Sends the agent's own opening message to users who are watching a conversation."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

from agent.context_engine.conversation_engine.policy import split_assistant_reply
from agent.context_engine.conversation_engine.state.service import list_threads
from agent.context_engine.engine import build_model_context_package
from agent.outputs.companion_response import structured_companion_reply
from agent.providers import _provider_messages, generate_agent_reply
from agent.providers.shared.messages import reply_window, summarized_through
from agent.runtime.orchestrator import _visible_companion_reply
from agent.shared.clock import utc_now
from agent.shared.timeline import day_part, humanize_gap, parse_time, user_zone
from realtime import conversation_event, realtime_hub
from storage import (
    get_conversation,
    get_proactive_enabled,
    get_user_profile,
    get_user_timezone,
    list_active_self_notes,
    resolve_self_notes,
    save_conversation,
)

from .policy import due_promise, nudge_block_reason, pick_thread, return_greeting_block_reason

logger = logging.getLogger(__name__)
DEFAULT_INTERVAL_SECONDS = 300.0

_PROACTIVE_INSTRUCTIONS = """

PROACTIVE MESSAGE
The user is online but quiet. First decide whether there is a natural reason to speak first.
- If the last exchange was in the middle of something (a story, a game, a task, a question
  waiting for them), or nothing specific is worth reopening, reply with exactly: SKIP
- Otherwise write ONE short message (one or two sentences) that refers to something concrete
  from the topic below or the recent chat. Never a generic opener, such as asking about their
  day or what is on their mind.
- Make it easy to ignore. No pressure, no guilt. Ask a light question only if it follows from
  the topic. Do not mention timers, follow-ups, memory or being automated.
Topic: {title}. What was said: {summary}. Suggested angle: {angle}.
"""
_CUE = "(The user has said nothing new. Send your own short opening message now.)"

_RETURN_INSTRUCTIONS = """

RETURN GREETING
The user just opened this chat after {gap} away. It is {day_part} for them. They have not
written yet. Write ONE short greeting (one or two sentences) that fits the time of day and the
gap. If one concrete thing is worth bringing up now (a promise of yours that is due, a plan they
had around this time, or where you left off), mention it; otherwise a warm, specific hello is
enough. No "how was your day" or "what's on your mind", no guilt about the absence, and do not
mention timers, memory or being automated.
"""
_RETURN_CUE = "(The user just came back and has not written yet. Greet them now.)"
_PROMISE_IN_GREETING = """Earlier you promised: "{promise}". It is due now, so bring it up in the greeting.
"""

_PROMISE_INSTRUCTIONS = """

PROMISE FOLLOW-UP
Earlier you promised the user: "{promise}". It is due now. Write ONE short message (one or two
sentences) that follows up on it naturally, the way a friend who remembered would. No pressure,
and do not mention reminders, timers, notes or being automated.
"""
# Lets the user type first; the greeting only goes out if they are still quiet.
DEFAULT_RETURN_GREETING_DELAY_SECONDS = 8.0
_pending_greetings: set[tuple[str, str]] = set()
_greeting_tasks: set[asyncio.Task[None]] = set()


def proactive_messaging_enabled() -> bool:
    """Deployment-level kill switch; each user also has their own off switch."""
    return os.getenv("PROACTIVE_MESSAGING_ENABLED", "true").strip().lower() != "false"


async def run_proactive_pass(*, now: datetime | None = None) -> int:
    """Try one nudge per live conversation and return how many were sent."""
    sent = 0
    for user_id, conversation_id in await realtime_hub.live_conversations():
        try:
            if await _nudge(user_id, conversation_id, now or utc_now()):
                sent += 1
        except Exception:
            logger.exception("agent.proactive.failed conversation_id=%s", conversation_id)
    return sent


def schedule_return_greeting(user_id: str, conversation_id: str) -> None:
    """Called when a user opens a chat: greet them shortly if they come back after a long gap."""
    key = (user_id, conversation_id)
    if not proactive_messaging_enabled() or key in _pending_greetings:
        return
    _pending_greetings.add(key)
    task = asyncio.create_task(_greet_after_delay(user_id, conversation_id))
    _greeting_tasks.add(task)
    task.add_done_callback(_greeting_tasks.discard)


def _return_greeting_delay() -> float:
    try:
        return max(0.0, float(os.getenv("PROACTIVE_RETURN_GREETING_DELAY_SECONDS", "8")))
    except ValueError:
        return DEFAULT_RETURN_GREETING_DELAY_SECONDS


async def _greet_after_delay(user_id: str, conversation_id: str) -> None:
    try:
        await asyncio.sleep(_return_greeting_delay())
        if (user_id, conversation_id) in await realtime_hub.live_conversations():
            await greet_on_return(user_id, conversation_id, utc_now())
    except Exception:
        logger.exception("agent.proactive.return_greeting_failed conversation_id=%s", conversation_id)
    finally:
        _pending_greetings.discard((user_id, conversation_id))


async def greet_on_return(user_id: str, conversation_id: str, now: datetime) -> bool:
    """Send one greeting to a user who opened the chat after a long silence."""
    conversation = _open_conversation(user_id, conversation_id)
    if conversation is None:
        return False
    messages = conversation["messages"]
    if return_greeting_block_reason(messages, now):
        return False
    last_sent = parse_time(messages[-1].get("created_at"))
    local_now = now.astimezone(user_zone(get_user_timezone(user_id)))
    promise = due_promise(list_active_self_notes(user_id), now)
    instructions = _RETURN_INSTRUCTIONS.format(
        gap=humanize_gap(now - last_sent), day_part=day_part(local_now)
    )
    if promise:
        instructions += _PROMISE_IN_GREETING.format(promise=promise["text"])
    reply = await _generate(
        conversation,
        user_id,
        user_text=promise["text"] if promise else _last_user_text(messages),
        instructions=instructions,
        cue=_RETURN_CUE,
    )
    if not reply:
        return False
    message = {
        "role": "assistant",
        "content": reply,
        "proactive": True,
        "proactive_kind": "return_greeting",
        "created_at": now.isoformat(),
    }
    return await _deliver_keeping_promise(user_id, conversation_id, len(messages), message, promise)


async def _deliver_keeping_promise(
    user_id: str,
    conversation_id: str,
    expected_count: int,
    message: dict[str, Any],
    promise: dict[str, Any] | None,
) -> bool:
    """Deliver; a promise raised in the message is marked done so it is never raised twice."""
    if promise:
        message["promise_note_id"] = promise["id"]
    delivered = await _deliver(
        user_id, conversation_id, expected_count=expected_count, message=message
    )
    if delivered and promise:
        resolve_self_notes(user_id, [(promise["id"], "done")])
    return delivered


def _open_conversation(user_id: str, conversation_id: str) -> dict[str, Any] | None:
    if not proactive_messaging_enabled() or not get_proactive_enabled(user_id):
        return None
    conversation = get_conversation(conversation_id, user_id)
    if not conversation or conversation.get("status") != "active":
        return None
    return conversation


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    return next(
        (str(m.get("content") or "") for m in reversed(messages) if m.get("role") == "user"), ""
    )


async def _nudge(user_id: str, conversation_id: str, now: datetime) -> bool:
    conversation = _open_conversation(user_id, conversation_id)
    if conversation is None:
        return False
    messages = conversation["messages"]
    if return_greeting_block_reason(messages, now) is None:
        # A user back after a long gap gets a greeting, not a topic nudge.
        return await greet_on_return(user_id, conversation_id, now)
    if nudge_block_reason(messages, now):
        return False
    promise = due_promise(list_active_self_notes(user_id), now)
    if promise:
        return await _follow_up_promise(user_id, conversation, promise, now)
    already_nudged = {m.get("thread_id") for m in messages if m.get("proactive")}
    thread = pick_thread(
        list_threads(user_id, statuses=("open",)), exclude_ids=already_nudged
    )
    if thread is None:
        return False

    reply = await _generate(
        conversation,
        user_id,
        user_text=thread.next_angle or thread.title,
        instructions=_PROACTIVE_INSTRUCTIONS.format(
            title=thread.title, summary=thread.summary, angle=thread.next_angle
        ),
        cue=_CUE,
    )
    if not reply:
        return False
    return await _deliver(
        user_id,
        conversation_id,
        expected_count=len(messages),
        message={
            "role": "assistant",
            "content": reply,
            "proactive": True,
            "proactive_kind": "topic_nudge",
            "thread_id": thread.id,
            "created_at": now.isoformat(),
        },
    )


async def _follow_up_promise(
    user_id: str, conversation: dict[str, Any], promise: dict[str, Any], now: datetime
) -> bool:
    reply = await _generate(
        conversation,
        user_id,
        user_text=promise["text"],
        instructions=_PROMISE_INSTRUCTIONS.format(promise=promise["text"]),
        cue=_CUE,
    )
    if not reply:
        return False
    message = {
        "role": "assistant",
        "content": reply,
        "proactive": True,
        "proactive_kind": "promise_follow_up",
        "created_at": now.isoformat(),
    }
    return await _deliver_keeping_promise(
        user_id, conversation["id"], len(conversation["messages"]), message, promise
    )


async def _deliver(
    user_id: str, conversation_id: str, *, expected_count: int, message: dict[str, Any]
) -> bool:
    # The user may have written while the model was thinking; re-read and never talk over them.
    latest = get_conversation(conversation_id, user_id)
    if not latest or len(latest["messages"]) != expected_count:
        return False
    reply = message["content"]
    latest["messages"] = [*latest["messages"], message]
    save_conversation(latest, user_id)
    index = len(latest["messages"]) - 1
    await realtime_hub.publish(
        conversation_event(
            "message.created",
            conversation_id,
            sequence=index,
            payload={
                "conversation_id": conversation_id,
                "message_index": index,
                "message": {
                    "role": "assistant",
                    "content": reply,
                    "created_at": message["created_at"],
                    "delivery_status": None,
                },
            },
        )
    )
    return True


async def _generate(
    conversation: dict[str, Any],
    user_id: str,
    *,
    user_text: str,
    instructions: str,
    cue: str,
) -> str | None:
    messages = conversation["messages"]
    package = await asyncio.to_thread(
        build_model_context_package,
        conversation_id=conversation["id"],
        user_text=user_text,
        user_id=user_id,
        user_profile=get_user_profile(user_id),
        model=conversation.get("agent_model"),
        agent_tone=conversation.get("agent_tone") or "auto",
        agent_name=conversation.get("agent_name"),
        style_source_id=conversation.get("agent_style_source_id"),
        user_message_index=len(messages),
        assistant_message_index=len(messages),
    )
    system_prompt = package.system_prompt + instructions
    raw = await generate_agent_reply(
        [
            *_provider_messages(
                reply_window(
                    messages,
                    summarized_through(package.context_sources),
                    (package.user_profile or {}).get("timezone"),
                )
            ),
            {"role": "user", "content": cue},
        ],
        conversation_id=conversation["id"],
        model=conversation.get("agent_model"),
        agent_mode=conversation.get("agent_mode") or "know_me",
        agent_tone=conversation.get("agent_tone") or "auto",
        agent_name=conversation.get("agent_name"),
        context_sources=package.context_sources,
        user_profile=package.user_profile,
        system_prompt=system_prompt,
        max_tokens=300,
    )
    text = _visible_companion_reply(raw, structured_companion_reply(raw))
    if _is_skip(text):
        return None
    parts = split_assistant_reply(text, user_text="")
    return parts[0].strip() if parts else None


def _is_skip(text: str) -> bool:
    """The model may decline to speak; SKIP is its answer for "no natural reason"."""
    return text.strip().strip(".!\"'`").upper() == "SKIP"


class ProactiveScheduler:
    """Runs proactive passes on an interval inside this process, next to its sockets."""

    def __init__(self, *, interval_seconds: float | None = None) -> None:
        self._interval = interval_seconds or float(
            os.getenv("PROACTIVE_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)
        )
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None and proactive_messaging_enabled():
            self._task = asyncio.create_task(self._loop(), name="proactive-messaging")

    async def shutdown(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await run_proactive_pass()
            except Exception:
                logger.exception("agent.proactive.pass_failed")


proactive_scheduler = ProactiveScheduler()
