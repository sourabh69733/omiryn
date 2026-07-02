from __future__ import annotations

from typing import Any

from agent.context_engine.context_snapshot import build_context_snapshot
from agent.context_engine.models import ModelContextPackage
from agent.context_engine.prompt_engine.builder import build_companion_system_prompt
from agent.context_engine.prompt_engine.registry import get_prompt_behavior_version
from agent.context_engine.query_intent import context_query_intent
from agent.context_engine.source_selection import build_reply_context


def build_model_context_package(
    *,
    conversation_id: str,
    user_text: str,
    user_id: str | None,
    user_profile: dict[str, Any] | None,
    model: str | None,
    agent_tone: str,
    agent_name: str | None,
    style_source_id: str | None,
    user_message_index: int,
    assistant_message_index: int,
    prompt_version_id: str | None = None,
) -> ModelContextPackage:
    prompt_version = get_prompt_behavior_version(prompt_version_id)
    reply_context = build_reply_context(
        conversation_id,
        user_text,
        user_id=user_id,
        user_profile=user_profile,
        style_source_id=style_source_id,
    )
    query_intent = context_query_intent(user_text)
    system_prompt = build_companion_system_prompt(
        context_sources=reply_context.context_sources,
        user_profile=reply_context.user_profile,
        agent_tone=agent_tone,
        agent_name=agent_name,
        prompt_version=prompt_version.version_id,
    )
    snapshot = build_context_snapshot(
        reply_context.context_sources,
        conversation_id=conversation_id,
        user_id=user_id,
        user_message_index=user_message_index,
        assistant_message_index=assistant_message_index,
        model=model,
        agent_tone=agent_tone,
        style_source_id=style_source_id,
        prompt_version=prompt_version.version_id,
        prompt_version_name=prompt_version.name,
    )
    return ModelContextPackage(
        system_prompt=system_prompt,
        context_sources=reply_context.context_sources,
        user_profile=reply_context.user_profile,
        prompt_version=prompt_version.version_id,
        prompt_version_name=prompt_version.name,
        query_intent=query_intent,
        snapshot=snapshot,
    )
