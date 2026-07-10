from __future__ import annotations

from collections import Counter
from typing import Any

from agent.context_engine.context_budget import budget_context_sources
from agent.context_engine.models import (
    ContextBlock,
    ContextQueryIntent,
    ConversationPlan,
    EmotionState,
    TopicState,
)

SNAPSHOT_PREVIEW_CHARS = 500


def build_context_snapshot(
    context_sources: list[dict[str, Any]],
    *,
    conversation_id: str,
    user_id: str | None,
    user_message_index: int,
    assistant_message_index: int,
    model: str | None,
    agent_tone: str,
    style_source_id: str | None,
    prompt_version: str | None = None,
    prompt_version_name: str | None = None,
) -> dict[str, Any]:
    budgeted_sources = budget_context_sources(context_sources)
    source_type_counts = Counter(
        str(item.source.get("source_type") or "context") for item in budgeted_sources
    )
    total_chars = sum(item.included_chars for item in budgeted_sources)
    source_summaries = [_source_snapshot(item) for item in budgeted_sources]
    flags = _snapshot_flags(source_summaries)

    return {
        "user_id": user_id,
        "conversation_id": conversation_id,
        "message_index": assistant_message_index,
        "summary": {
            "user_message_index": user_message_index,
            "assistant_message_index": assistant_message_index,
            "model": model,
            "agent_tone": agent_tone,
            "prompt_version": prompt_version,
            "prompt_version_name": prompt_version_name,
            "style_source_id": style_source_id,
            "source_count": len(context_sources),
            "included_source_count": len(budgeted_sources),
            "context_chars": total_chars,
            "rough_context_tokens": _rough_tokens(total_chars),
            "source_type_counts": dict(source_type_counts),
            **flags,
        },
        "context": {
            "sources": source_summaries,
            "budget": {
                "context_chars": total_chars,
                "rough_context_tokens": _rough_tokens(total_chars),
            },
        },
    }


def build_context_snapshot_v2(
    context_sources: list[dict[str, Any]],
    *,
    conversation_id: str,
    user_id: str | None,
    user_message_index: int,
    assistant_message_index: int,
    model: str | None,
    agent_tone: str,
    style_source_id: str | None,
    prompt_version: str | None,
    prompt_version_name: str | None,
    query_intent: ContextQueryIntent,
    emotion_state: EmotionState,
    topic_states: list[TopicState],
    conversation_plan: ConversationPlan,
) -> dict[str, Any]:
    budgeted_sources = budget_context_sources(context_sources)
    included_ids = {
        _source_identity_for_snapshot(item.source, item.original_index)
        for item in budgeted_sources
    }
    selected_blocks = [
        _context_block_snapshot(block)
        for block in _source_context_blocks(budgeted_sources)
    ]
    skipped_blocks = [
        _skipped_source_snapshot(source, index)
        for index, source in enumerate(context_sources)
        if _source_identity_for_snapshot(source, index) not in included_ids
    ]
    source_type_counts = Counter(
        str(item.source.get("source_type") or "context") for item in budgeted_sources
    )
    total_chars = sum(item.included_chars for item in budgeted_sources)
    source_summaries = [_source_snapshot(item) for item in budgeted_sources]
    flags = _snapshot_flags(source_summaries)

    return {
        "user_id": user_id,
        "conversation_id": conversation_id,
        "message_index": assistant_message_index,
        "summary": {
            "engine_version": "context_v2",
            "user_message_index": user_message_index,
            "assistant_message_index": assistant_message_index,
            "model": model,
            "agent_tone": agent_tone,
            "prompt_version": prompt_version,
            "prompt_version_name": prompt_version_name,
            "style_source_id": style_source_id,
            "source_count": len(context_sources),
            "included_source_count": len(budgeted_sources),
            "skipped_source_count": len(skipped_blocks),
            "context_chars": total_chars,
            "rough_context_tokens": _rough_tokens(total_chars),
            "source_type_counts": dict(source_type_counts),
            "intent_labels": list(query_intent.labels),
            "intent_confidence": query_intent.confidence,
            "conversation_move": conversation_plan.current_move,
            "response_mode": conversation_plan.response_mode,
            "emotion": emotion_state.emotion,
            "emotion_confidence": emotion_state.confidence,
            "active_topic": conversation_plan.active_topic,
            **flags,
        },
        "context": {
            "intent": {
                "labels": list(query_intent.labels),
                "confidence": query_intent.confidence,
                "entities": list(query_intent.entities),
                "prefer_structured_whatsapp": query_intent.prefer_structured_whatsapp,
                "is_low_information": query_intent.is_low_information,
            },
            "emotion_state": _emotion_state_snapshot(emotion_state),
            "topic_state": [_topic_state_snapshot(state) for state in topic_states],
            "conversation_plan": _conversation_plan_snapshot(conversation_plan),
            "blocks": selected_blocks,
            "skipped_blocks": skipped_blocks,
            "sources": source_summaries,
            "budget": {
                "context_chars": total_chars,
                "rough_context_tokens": _rough_tokens(total_chars),
            },
        },
    }


def _source_snapshot(item: Any) -> dict[str, Any]:
    source = item.source
    content = item.content
    return {
        "id": source.get("id"),
        "source_type": source.get("source_type") or "context",
        "title": source.get("title") or "Untitled source",
        "priority": item.priority,
        "original_chars": item.original_chars,
        "included_chars": item.included_chars,
        "rough_tokens": _rough_tokens(item.included_chars),
        "truncated": item.truncated,
        "metadata": _safe_metadata(source.get("metadata") or {}),
        "preview": content[:SNAPSHOT_PREVIEW_CHARS],
    }


def _source_context_blocks(budgeted_sources: list[Any]) -> list[ContextBlock]:
    blocks: list[ContextBlock] = []
    for item in budgeted_sources:
        source = item.source
        source_type = str(source.get("source_type") or "context")
        blocks.append(
            ContextBlock(
                id=_source_identity_for_snapshot(source, item.original_index),
                title=str(source.get("title") or "Untitled source"),
                content=item.content,
                source=source_type,
                priority=item.priority,
                position=_block_position(source_type),
                token_estimate=_rough_tokens(item.included_chars),
                include_reason=_include_reason(source_type),
                metadata=_safe_metadata(source.get("metadata") or {}),
            )
        )
    return blocks


def _context_block_snapshot(block: ContextBlock) -> dict[str, Any]:
    return {
        "id": block.id,
        "title": block.title,
        "source": block.source,
        "priority": block.priority,
        "position": block.position,
        "rough_tokens": block.token_estimate,
        "include_reason": block.include_reason,
        "metadata": block.metadata,
        "preview": block.content[:SNAPSHOT_PREVIEW_CHARS],
    }


def _skipped_source_snapshot(source: dict[str, Any], index: int) -> dict[str, Any]:
    content = str(source.get("content") or "")
    return {
        "id": _source_identity_for_snapshot(source, index),
        "title": source.get("title") or "Untitled source",
        "source": source.get("source_type") or "context",
        "skip_reason": "Dropped by context budget or source limit.",
        "original_chars": len(content),
        "rough_tokens": _rough_tokens(len(content)),
        "metadata": _safe_metadata(source.get("metadata") or {}),
    }


def _topic_state_snapshot(state: TopicState) -> dict[str, Any]:
    return {
        "topic_id": state.topic_id,
        "label": state.label,
        "bucket": state.bucket,
        "status": state.status,
        "depth": state.depth,
        "last_seen_turns_ago": state.last_seen_turns_ago,
        "repeat_count": state.repeat_count,
        "user_interest": state.user_interest,
    }


def _conversation_plan_snapshot(plan: ConversationPlan) -> dict[str, Any]:
    return {
        "current_move": plan.current_move,
        "response_mode": plan.response_mode,
        "active_topic": plan.active_topic,
        "avoid_topics": list(plan.avoid_topics),
        "suggested_topics": list(plan.suggested_topics),
        "data_targets": list(plan.data_targets),
        "tone_instruction": plan.tone_instruction,
        "reason": plan.reason,
    }


def _emotion_state_snapshot(state: EmotionState) -> dict[str, Any]:
    return {
        "emotion": state.emotion,
        "intensity": state.intensity,
        "confidence": state.confidence,
        "need": state.need,
        "strategy": state.strategy,
        "response_mode": state.response_mode,
        "evidence": list(state.evidence),
    }


def _block_position(source_type: str) -> str:
    if source_type == "agent_behavior_rules":
        return "start"
    if source_type == "data_points":
        return "start"
    if source_type in {"whatsapp_structured_context", "friend_style", "whatsapp_chat"}:
        return "middle"
    return "middle"


def _include_reason(source_type: str) -> str:
    reasons = {
        "agent_behavior_rules": "High-priority user-taught agent behavior rules.",
        "data_points": "Relevant learned data points for this turn.",
        "whatsapp_structured_context": "Relevant uploaded WhatsApp context for topics, people, or style.",
        "friend_style": "Selected style source.",
        "whatsapp_chat": "Selected WhatsApp style/context source.",
        "llm_profile": "Stored profile context matched the user message.",
    }
    return reasons.get(source_type, "Relevant attached context matched the user message.")


def _source_identity_for_snapshot(source: dict[str, Any], index: int) -> str:
    return str(source.get("id") or (source.get("metadata") or {}).get("import_id") or f"source-{index}")


def _snapshot_flags(source_summaries: list[dict[str, Any]]) -> dict[str, bool]:
    combined = "\n".join(str(source.get("preview") or "") for source in source_summaries)
    source_types = {str(source.get("source_type") or "") for source in source_summaries}
    return {
        "used_data_points": "data_points" in source_types,
        "used_agent_behavior_rules": "agent_behavior_rules" in source_types,
        "used_structured_whatsapp": "whatsapp_structured_context" in source_types,
        "used_style_context": bool({"friend_style", "whatsapp_chat"} & source_types),
        "used_style_guide": "Style adaptation guide" in combined,
        "used_whatsapp_chunks": "Relevant message chunks:" in combined,
    }


def _safe_metadata(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    allowed_keys = {
        "context_source_id",
        "import_id",
        "original_source_id",
        "point_count",
        "query_intent",
        "retrieved_chunk_count",
        "rule_count",
        "rule_ids",
        "selected_sender",
        "style_kind",
        "style_name",
    }
    return {key: value for key, value in metadata.items() if key in allowed_keys}


def _rough_tokens(chars: int) -> int:
    return round(chars / 4) if chars else 0
