"""Puts the reply context together from the sources in `context_engine/sources`, in the order the
prompt expects."""

from __future__ import annotations

from typing import Any

from agent.config import agent_pipeline_config
from agent.context_engine.contracts.models import AgentContext, ContextQueryIntent, ThreadGuidance
from agent.context_engine.threads import conversation_thread_context_sources, conversation_thread_guidance
from agent.context_engine.understanding.rules.intent import context_query_intent
from agent.context_engine.shared.text import source_identity
from agent.context_engine.sources.attached import (
    STYLE_CONTEXT_SOURCE_TYPES,
    relevant_attached_sources,
    selected_style_sources,
    source_matches_id,
    valid_attached_sources,
)
from agent.context_engine.sources.legacy import (
    AGENT_BEHAVIOR_RULES_SOURCE_TYPE,
    DATA_POINT_SOURCE_TYPE,
    behavior_rule_sources,
    data_point_sources,
)
from agent.context_engine.sources.memories import memory_sources
from agent.context_engine.sources.might_fit import might_fit_sources
from agent.context_engine.sources.open_questions import open_question_sources
from agent.context_engine.sources.past_lines import past_lines_sources
from agent.context_engine.sources.reply_feedback import reply_feedback_sources
from agent.context_engine.sources.self_notes import self_note_sources
from agent.context_engine.sources.sessions import recent_sessions_sources
from agent.context_engine.sources.shared_chats import names_uploaded_person, uploaded_chat_sources
from agent.context_engine.sources.summary import conversation_summary_sources
from agent.context_engine.sources.texting_style import texting_style_sources
from agent.context_engine.sources.user_card import user_card_sources
from agent.context_engine.sources.whatsapp import WHATSAPP_STRUCTURED_SOURCE_TYPE, own_upload, structured_whatsapp_sources
from storage import list_context_sources


def build_reply_context(
    conversation_id: str,
    user_text: str,
    *,
    user_id: str | None = None,
    user_profile: dict[str, Any] | None = None,
    style_source_id: str | None = None,
    strict_intent: bool = False,
    memory_query_embedding: dict[str, Any] | None = None,
) -> AgentContext:
    thread_guidance = conversation_thread_guidance(
        conversation_id,
        user_id,
        user_text,
    )
    return AgentContext(
        user_profile=user_profile,
        context_sources=build_reply_context_sources(
            conversation_id,
            style_source_id,
            user_text,
            user_id,
            strict_intent=strict_intent,
            thread_guidance=thread_guidance,
            memory_query_embedding=memory_query_embedding,
        ),
        thread_guidance=thread_guidance,
    )


def build_reply_context_sources(
    conversation_id: str,
    style_source_id: str | None,
    user_text: str,
    user_id: str | None = None,
    *,
    strict_intent: bool = False,
    thread_guidance: ThreadGuidance | None = None,
    memory_query_embedding: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    pipeline = agent_pipeline_config()
    query_intent = context_query_intent(user_text, strict_whatsapp=strict_intent)
    all_sources = list_context_sources(conversation_id, user_id)
    attached_sources = valid_attached_sources(all_sources, user_id)
    selected_styles = selected_style_sources(all_sources, style_source_id)
    retrieved_sources = relevant_attached_sources(attached_sources, user_text)
    agent_behavior_sources = (
        []
        if pipeline.memory_contract_version == 3
        else behavior_rule_sources(user_id)
    )
    past_lines: list[dict[str, Any]] = []
    if pipeline.memory_contract_version == 3:
        durable_memory_sources = memory_sources(
            user_id,
            user_text,
            memory_query_embedding,
            broad="profile_recall" in query_intent.labels,
        )
        past_lines = past_lines_sources(user_id, conversation_id, user_text, memory_query_embedding)
        # A question about someone (or one with real past lines to answer it) gets no unrelated
        # memories to weave in: one subject at a time.
        if not (past_lines or names_uploaded_person(user_id, user_text, conversation_id)):
            durable_memory_sources += might_fit_sources(conversation_id, user_id, durable_memory_sources)
    else:
        durable_memory_sources = data_point_sources(user_id, user_text)
    # In v3 a chat the user uploaded of their own reaches replies through shared_chats and search;
    # the older chunk retrieval stays only for a friend's style they chose for Omi to copy.
    is_own_upload = own_upload if pipeline.memory_contract_version == 3 else (lambda source: False)
    whatsapp_sources = structured_whatsapp_sources(
        [source for source in all_sources if not is_own_upload(source)],
        [source for source in attached_sources if not is_own_upload(source)],
        selected_styles,
        user_text,
        user_id,
        query_intent,
    )
    continuity_sources = (
        user_card_sources(user_id)
        + recent_sessions_sources(conversation_id, user_id)
        + conversation_summary_sources(conversation_id, user_id)
        + self_note_sources(user_id, user_text)
        + open_question_sources(conversation_id, user_id)
        + reply_feedback_sources(user_id)
        + (uploaded_chat_sources(user_id, user_text, conversation_id) if pipeline.memory_contract_version == 3 else [])
        + past_lines
    ) + conversation_thread_context_sources(
        conversation_id,
        user_id,
        user_text,
        guidance=thread_guidance,
    )

    if selected_styles:
        selected_style_ids = {source_identity(source) for source in selected_styles}
        ordered_sources = continuity_sources + _ordered_memory_context_sources(
            agent_behavior_sources,
            durable_memory_sources,
            whatsapp_sources,
            query_intent,
        )
        return (
            selected_styles
            + ordered_sources
            + [
                source
                for source in retrieved_sources
                if source_identity(source) not in selected_style_ids
            ]
            + texting_style_sources(user_id)
        )

    return continuity_sources + (
        _ordered_memory_context_sources(
            agent_behavior_sources,
            durable_memory_sources,
            whatsapp_sources,
            query_intent,
        )
        + retrieved_sources
        + texting_style_sources(user_id)
    )


def build_profile_extraction_context_sources(
    conversation_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    return [
        source
        for source in valid_attached_sources(
            list_context_sources(conversation_id, user_id),
            user_id,
        )
        if source.get("source_type") not in STYLE_CONTEXT_SOURCE_TYPES
    ]


def selected_style_source_exists(
    conversation_id: str,
    style_source_id: str | None,
    user_id: str | None = None,
) -> bool:
    if not style_source_id:
        return True
    return any(
        source_matches_id(source, style_source_id)
        and source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
        for source in list_context_sources(conversation_id, user_id)
    )


def _ordered_memory_context_sources(
    agent_behavior_sources: list[dict[str, Any]],
    durable_memory_sources: list[dict[str, Any]],
    structured_whatsapp_sources: list[dict[str, Any]],
    query_intent: ContextQueryIntent,
) -> list[dict[str, Any]]:
    if query_intent.prefer_structured_whatsapp:
        return agent_behavior_sources + structured_whatsapp_sources + durable_memory_sources
    return agent_behavior_sources + durable_memory_sources + structured_whatsapp_sources


__all__ = [
    "AGENT_BEHAVIOR_RULES_SOURCE_TYPE",
    "DATA_POINT_SOURCE_TYPE",
    "STYLE_CONTEXT_SOURCE_TYPES",
    "WHATSAPP_STRUCTURED_SOURCE_TYPE",
    "build_profile_extraction_context_sources",
    "build_reply_context",
    "build_reply_context_sources",
    "selected_style_source_exists",
]
