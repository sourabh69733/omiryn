from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.context import build_reply_context
from agent.memory import capture_profile_facts_from_user_message
from agent.providers import assess_user_message_quality, generate_agent_reply


@dataclass(frozen=True)
class AgentTurnResult:
    messages: list[dict[str, Any]]
    quality_valid: bool


async def run_agent_turn(
    *,
    conversation_id: str,
    messages: list[dict[str, Any]],
    user_text: str,
    user_id: str | None,
    user_profile: dict[str, Any] | None,
    model: str | None,
    agent_mode: str,
    agent_tone: str,
    style_source_id: str | None,
    agent_name: str | None = None,
) -> AgentTurnResult:
    updated_messages = [dict(message) for message in messages]
    user_message: dict[str, Any] = {"role": "user", "content": user_text}
    quality = assess_user_message_quality(updated_messages + [user_message])
    quality_valid = bool(quality["valid"])
    if not quality_valid:
        user_message["quality"] = "low_information"

    updated_messages.append(user_message)
    capture_profile_facts_from_user_message(
        conversation_id,
        user_id,
        user_text,
        len(updated_messages) - 1,
        quality_valid,
    )
    context = build_reply_context(
        conversation_id,
        user_text,
        user_id=user_id,
        user_profile=user_profile,
        style_source_id=style_source_id,
    )
    reply = await generate_agent_reply(
        updated_messages,
        conversation_id=conversation_id,
        model=model,
        agent_mode=agent_mode,
        agent_tone=agent_tone,
        agent_name=agent_name,
        context_sources=context.context_sources,
        user_profile=context.user_profile,
    )
    updated_messages.append({"role": "assistant", "content": reply})
    return AgentTurnResult(messages=updated_messages, quality_valid=quality_valid)
