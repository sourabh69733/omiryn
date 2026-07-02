from __future__ import annotations

from collections import Counter
from typing import Any

from agent.context_engine.context_budget import budget_context_sources

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


def _snapshot_flags(source_summaries: list[dict[str, Any]]) -> dict[str, bool]:
    combined = "\n".join(str(source.get("preview") or "") for source in source_summaries)
    source_types = {str(source.get("source_type") or "") for source in source_summaries}
    return {
        "used_data_points": "data_points" in source_types,
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
        "selected_sender",
        "style_kind",
        "style_name",
    }
    return {key: value for key, value in metadata.items() if key in allowed_keys}


def _rough_tokens(chars: int) -> int:
    return round(chars / 4) if chars else 0
