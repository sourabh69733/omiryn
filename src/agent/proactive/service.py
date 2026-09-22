"""Sends the agent's own opening message to users who are watching a conversation."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

from agent.context_engine.conversation_engine.policy import split_assistant_reply
from agent.context_engine.conversation_engine.state.models import ConversationThread
from agent.context_engine.conversation_engine.state.service import list_threads
from agent.context_engine.engine import build_model_context_package
from agent.outputs.companion_response import structured_companion_reply
from agent.providers import _provider_messages, generate_agent_reply
from agent.providers.shared.messages import reply_window, summarized_through
from agent.runtime.orchestrator import _visible_companion_reply
from agent.shared.clock import utc_now
from realtime import conversation_event, realtime_hub
from storage import (
    get_conversation,
    get_proactive_enabled,
    get_user_profile,
    save_conversation,
)

from .policy import nudge_block_reason, pick_thread

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


async def _nudge(user_id: str, conversation_id: str, now: datetime) -> bool:
    if not get_proactive_enabled(user_id):
        return False
    conversation = get_conversation(conversation_id, user_id)
    if not conversation or conversation.get("status") != "active":
        return False
    messages = conversation["messages"]
    if nudge_block_reason(messages, now):
        return False
    already_nudged = {m.get("thread_id") for m in messages if m.get("proactive")}
    thread = pick_thread(
        list_threads(user_id, statuses=("open",)), exclude_ids=already_nudged
    )
    if thread is None:
        return False

    reply = await _generate(conversation, thread, user_id)
    if not reply:
        return False

    # The user may have written while the model was thinking; re-read and never talk over them.
    latest = get_conversation(conversation_id, user_id)
    if not latest or len(latest["messages"]) != len(messages):
        return False
    message = {
        "role": "assistant",
        "content": reply,
        "proactive": True,
        "thread_id": thread.id,
        "created_at": now.isoformat(),
    }
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
    conversation: dict[str, Any], thread: ConversationThread, user_id: str
) -> str | None:
    messages = conversation["messages"]
    package = await asyncio.to_thread(
        build_model_context_package,
        conversation_id=conversation["id"],
        user_text=thread.next_angle or thread.title,
        user_id=user_id,
        user_profile=get_user_profile(user_id),
        model=conversation.get("agent_model"),
        agent_tone=conversation.get("agent_tone") or "auto",
        agent_name=conversation.get("agent_name"),
        style_source_id=conversation.get("agent_style_source_id"),
        user_message_index=len(messages),
        assistant_message_index=len(messages),
    )
    system_prompt = package.system_prompt + _PROACTIVE_INSTRUCTIONS.format(
        title=thread.title, summary=thread.summary, angle=thread.next_angle
    )
    raw = await generate_agent_reply(
        [
            *_provider_messages(
                reply_window(
                    messages,
                    summarized_through(package.context_sources),
                    (package.user_profile or {}).get("timezone"),
                )
            ),
            {"role": "user", "content": _CUE},
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
