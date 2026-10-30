"""Sends the agent's own opening message to users who are watching a conversation."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

from agent.context_engine.policy import split_assistant_reply
from agent.context_engine.policy.freshness import (
    recent_assistant_replies,
    rewrite_instruction,
    stale_reply_reason,
    without_copied_replies,
)
from agent.context_engine.threads.service import list_threads
from agent.context_engine.engine import build_model_context_package
from agent.outputs.companion_response import structured_companion_reply
from agent.providers import _provider_messages, generate_agent_reply
from agent.providers.shared.messages import reply_window, summarized_through
from agent.providers.shared.model_catalog import preferred_reply_model
from agent.runtime.steps import visible_reply
from agent.shared.clock import utc_now
from agent.shared.timeline import day_part, humanize_gap, parse_time, relative_day, user_zone
from realtime import conversation_event, realtime_hub
from storage import (
    get_conversation,
    get_proactive_enabled,
    get_user_profile,
    get_user_timezone,
    list_active_self_notes,
    list_agent_memories,
    mark_agent_memory_followed_up,
    resolve_self_notes,
    update_conversation,
)

from .policy import (
    due_event,
    due_promise,
    nudge_block_reason,
    pick_thread,
    return_greeting_block_reason,
)

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
had around this time, or something they left half done), mention it; otherwise a warm, specific
hello is enough. Never ask about something they already told you is done, settled or not to bring up. No "how was your day" or "what's on your mind", no guilt about the absence, and do not
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

_EVENT_INSTRUCTIONS = """

PLAN FOLLOW-UP
Before it happened, the user told you about this: "{event}" ({when}). It has passed now. If the
recent chat shows they already told you how it went, that it was called off, or it is not
something a friend would ask about, reply with exactly: SKIP
Otherwise write ONE short message (one or two sentences) asking how it went, the way a friend
who remembered would. Name it concretely. No pressure, and do not mention reminders, memory,
notes or being automated.
"""
_EVENT_IN_GREETING = """Before it happened, they told you about this: "{event}" ({when}). It has passed. Unless they
already told you how it went, ask about it in the greeting.
"""
# Lets the user type first; the greeting only goes out if they are still quiet.
DEFAULT_RETURN_GREETING_DELAY_SECONDS = 8.0
RETURN_GREETING_JOB = "return_greeting"
# A job that finds the user watching on another instance goes back to the queue this soon, so
# the instance holding their socket picks it up and can push the message to them.
_HAND_OVER_SECONDS = 3.0


def proactive_messaging_enabled() -> bool:
    """Deployment-level kill switch; each user also has their own off switch."""
    return os.getenv("PROACTIVE_MESSAGING_ENABLED", "true").strip().lower() != "false"


async def run_proactive_pass(*, now: datetime | None = None) -> int:
    """Try one nudge per live conversation and return how many were sent."""
    # Imported here: the away pass builds on this module.
    from .away import run_away_follow_ups

    now = now or utc_now()
    sent = 0
    live = await realtime_hub.live_conversations()
    for user_id, conversation_id in live:
        try:
            if await _nudge(user_id, conversation_id, now):
                sent += 1
        except Exception:
            logger.exception("agent.proactive.failed conversation_id=%s", conversation_id)
    return sent + await run_away_follow_ups({user_id for user_id, _ in live}, now)


def schedule_return_greeting(user_id: str, conversation_id: str) -> None:
    """Called when a user opens a chat: greet them shortly if they come back after a long gap.

    A durable job, not an in-process timer: it survives a restart, and on Cloud Run it runs
    while the open socket keeps the CPU on. Opening the chat again only moves its time.
    """
    if not proactive_messaging_enabled():
        return
    from agent.jobs.queue import schedule_job

    schedule_job(RETURN_GREETING_JOB, user_id, conversation_id, delay_seconds=_return_greeting_delay())


def _return_greeting_delay() -> float:
    try:
        return max(0.0, float(os.getenv("PROACTIVE_RETURN_GREETING_DELAY_SECONDS", "8")))
    except ValueError:
        return DEFAULT_RETURN_GREETING_DELAY_SECONDS


async def run_return_greeting_job(job: dict[str, Any]) -> bool:
    """Greet if the user is still watching here; hand over if they are watching elsewhere."""
    user_id, conversation_id = str(job["user_id"]), str(job["conversation_id"])
    where = await watching(user_id, conversation_id)
    if where == "elsewhere":
        hand_over(RETURN_GREETING_JOB, user_id, conversation_id)
        return False
    if where is None:
        return False
    return await greet_on_return(user_id, conversation_id, utc_now())


async def watching(user_id: str, conversation_id: str) -> str | None:
    """"here" when this instance holds a socket on the chat, "elsewhere" when only another one
    does, None when nobody is watching."""
    key = (user_id, conversation_id)
    if key in await realtime_hub.live_conversations():
        return "here"
    try:
        live = await realtime_hub.live_everywhere()
    except Exception:
        logger.warning("agent.proactive.presence_read_failed", exc_info=True)
        return None
    return "elsewhere" if live.get(key) else None


def hand_over(kind: str, user_id: str, conversation_id: str) -> None:
    """Put a job back for another instance, the one with the user's socket, to run shortly."""
    from agent.jobs.queue import schedule_job

    schedule_job(kind, user_id, conversation_id, delay_seconds=_HAND_OVER_SECONDS)


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
    event = _due_event(user_id, now)
    if event:
        instructions += _EVENT_IN_GREETING.format(**_event_facts(event, user_id, now))
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
    if event:
        message["event_memory_id"] = event["id"]
    delivered = await _deliver_keeping_promise(user_id, conversation_id, len(messages), message, promise)
    if delivered and event:
        mark_agent_memory_followed_up(event["id"], user_id, now)
    return delivered


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
    # The user put an archived chat away, or it is temporary; Omi does not greet or nudge there.
    if (
        not conversation
        or conversation.get("status") != "active"
        or conversation.get("archived_at")
        or conversation.get("temporary")
        or conversation.get("import_source_id")
    ):
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
    event = _due_event(user_id, now)
    if event:
        return await follow_up_event(user_id, conversation, event, now) is not None
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
        show_typing=False,
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


def _due_event(user_id: str, now: datetime) -> dict[str, Any] | None:
    return due_event(list_agent_memories(user_id), now, user_zone(get_user_timezone(user_id)))


def _event_facts(event: dict[str, Any], user_id: str, now: datetime) -> dict[str, str]:
    zone = user_zone(get_user_timezone(user_id))
    occurred = parse_time(event.get("occurred_at")) or now
    text = event.get("statement") or str(event.get("value") or "")
    return {
        "event": text,
        "when": relative_day(occurred.astimezone(zone).date(), now.astimezone(zone).date()),
    }


async def follow_up_event(
    user_id: str, conversation: dict[str, Any], event: dict[str, Any], now: datetime
) -> dict[str, Any] | None:
    """Ask how a plan went; returns the delivered message, or None when nothing went out.

    The plan is marked once asked, and also when the model declines, so it is weighed only once.
    """
    facts = _event_facts(event, user_id, now)
    reply = await _generate(
        conversation,
        user_id,
        user_text=facts["event"],
        instructions=_EVENT_INSTRUCTIONS.format(**facts),
        cue=_CUE,
        show_typing=False,
    )
    if not reply:
        mark_agent_memory_followed_up(event["id"], user_id, now)
        return None
    message = {
        "role": "assistant",
        "content": reply,
        "proactive": True,
        "proactive_kind": "event_follow_up",
        "event_memory_id": event["id"],
        "created_at": now.isoformat(),
    }
    if not await _deliver(
        user_id, conversation["id"], expected_count=len(conversation["messages"]), message=message
    ):
        return None
    mark_agent_memory_followed_up(event["id"], user_id, now)
    return message


async def _deliver(
    user_id: str, conversation_id: str, *, expected_count: int, message: dict[str, Any]
) -> bool:
    return await deliver_messages(
        user_id, conversation_id, expected_count=expected_count, new_messages=[message]
    )


async def deliver_messages(
    user_id: str,
    conversation_id: str,
    *,
    expected_count: int,
    new_messages: list[dict[str, Any]],
) -> bool:
    """Append agent-initiated bubbles and push them live, unless the chat moved on meanwhile."""
    # The user may have written while the model was thinking; the count is checked under the
    # row lock, so Omi never talks over them and never overwrites a reply saved meanwhile.
    if not new_messages:
        return False

    added = False

    def add(messages: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        nonlocal added
        if len(messages) != expected_count:
            return None
        added = True
        return [*messages, *new_messages]

    if not update_conversation(conversation_id, user_id, add) or not added:
        return False
    for index, message in enumerate(new_messages, start=expected_count):
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
                        "content": message["content"],
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
    show_typing: bool = True,
) -> str | None:
    """One short bubble for a nudge or greeting; None when the model declines."""
    text = await generate_initiative_text(
        conversation,
        user_id,
        user_text=user_text,
        instructions=instructions,
        cue=cue,
        show_typing=show_typing,
    )
    parts = split_assistant_reply(text, user_text="") if text else []
    return parts[0].strip() if parts else None


async def generate_initiative_text(
    conversation: dict[str, Any],
    user_id: str,
    *,
    user_text: str,
    instructions: str,
    cue: str,
    max_tokens: int = 300,
    show_typing: bool = True,
) -> str | None:
    """The full visible reply for an agent-initiated message; None on SKIP.

    With show_typing the chat shows typing dots while the model writes, as it does for replies.
    Messages the model may decline (topic nudges) skip it: dots that end in nothing feel odd.
    """
    if show_typing:
        await _publish_typing(conversation["id"], True)
    try:
        text = await _initiative_text(
            conversation,
            user_id,
            user_text=user_text,
            instructions=instructions,
            cue=cue,
            max_tokens=max_tokens,
        )
        return None if _is_skip(text) else text
    finally:
        if show_typing:
            await _publish_typing(conversation["id"], False)


async def _publish_typing(conversation_id: str, active: bool) -> None:
    await realtime_hub.publish(
        conversation_event(
            "agent.typing",
            conversation_id,
            payload={"conversation_id": conversation_id, "active": active},
        )
    )


async def _initiative_text(
    conversation: dict[str, Any],
    user_id: str,
    *,
    user_text: str,
    instructions: str,
    cue: str,
    max_tokens: int,
) -> str:
    messages = conversation["messages"]
    package = await asyncio.to_thread(
        build_model_context_package,
        conversation_id=conversation["id"],
        user_text=user_text,
        user_id=user_id,
        user_profile=get_user_profile(user_id),
        model=preferred_reply_model(user_id, conversation.get("agent_model")),
        agent_tone=conversation.get("agent_tone") or "auto",
        agent_name=conversation.get("agent_name"),
        style_source_id=conversation.get("agent_style_source_id"),
        user_message_index=len(messages),
        assistant_message_index=len(messages),
    )
    system_prompt = package.system_prompt + instructions
    history = reply_window(
        messages,
        summarized_through(package.context_sources),
        (package.user_profile or {}).get("timezone"),
    )

    async def write(window: list[dict[str, Any]], note: str | None = None) -> str:
        raw = await generate_agent_reply(
            [
                *_provider_messages(window),
                {"role": "user", "content": cue},
                *([{"role": "system", "content": note}] if note else []),
            ],
            conversation_id=conversation["id"],
            model=preferred_reply_model(user_id, conversation.get("agent_model")),
            agent_mode=conversation.get("agent_mode") or "know_me",
            agent_tone=conversation.get("agent_tone") or "auto",
            agent_name=conversation.get("agent_name"),
            context_sources=package.context_sources,
            user_profile=package.user_profile,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
        )
        return visible_reply(raw, structured_companion_reply(raw))

    text = await write(history)
    earlier = recent_assistant_replies(messages)
    reason = None if _is_skip(text) else stale_reply_reason(text, earlier)
    if reason is None:
        return text
    # Seen live: a greeting copied, word for word, the last greeting in the history. The retry
    # does not see what it copied; a message nobody asked for is dropped rather than repeated.
    text = await write(
        without_copied_replies(history, text), rewrite_instruction(text, reason, quote_draft=False)
    )
    return "SKIP" if stale_reply_reason(text, earlier) else text


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
