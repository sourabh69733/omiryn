from __future__ import annotations

from typing import Any

from agent.context_engine.context_snapshot import build_context_snapshot, build_context_snapshot_v2
from agent.context_engine.conversation_planner import build_conversation_plan
from agent.context_engine.emotion_engine import detect_emotion_state
from agent.context_engine.models import ModelContextPackage
from agent.context_engine.prompt_engine.builder import (
    build_companion_system_prompt,
    build_companion_system_prompt_v2,
)
from agent.context_engine.prompt_engine.registry import get_prompt_behavior_version
from agent.context_engine.query_intent import context_query_intent
from agent.context_engine.source_selection import build_reply_context
from agent.context_engine.topic_state import build_topic_state
from storage import get_conversation


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
    if prompt_version.version_id == "v2":
        planning_messages = _planning_messages(conversation_id, user_id, user_text)
        emotion_state = detect_emotion_state(
            user_text=user_text,
            messages=planning_messages,
            intent=query_intent,
        )
        topic_states = build_topic_state(planning_messages, user_text, query_intent)
        conversation_plan = build_conversation_plan(
            user_text=user_text,
            intent=query_intent,
            topic_states=topic_states,
            emotion_state=emotion_state,
        )
        system_prompt = build_companion_system_prompt_v2(
            context_sources=reply_context.context_sources,
            user_profile=reply_context.user_profile,
            agent_tone=agent_tone,
            agent_name=agent_name,
            prompt_version=prompt_version,
            query_intent=query_intent,
            emotion_state=emotion_state,
            topic_states=topic_states,
            conversation_plan=conversation_plan,
        )
        snapshot = build_context_snapshot_v2(
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
            query_intent=query_intent,
            emotion_state=emotion_state,
            topic_states=topic_states,
            conversation_plan=conversation_plan,
        )
    else:
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


def _planning_messages(
    conversation_id: str,
    user_id: str | None,
    user_text: str,
) -> list[dict[str, Any]]:
    conversation = get_conversation(conversation_id, user_id)
    messages = [dict(message) for message in (conversation or {}).get("messages") or []]
    messages.append({"role": "user", "content": user_text})
    return messages
