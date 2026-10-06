"""Applies size and priority limits while assembling dynamic model context."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

# Room for the user card and conversation summary on top of the five earlier source slots.
CONTEXT_SOURCE_LIMIT = int(os.getenv("AGENT_CONTEXT_SOURCE_LIMIT", "9"))
CONTEXT_TOTAL_CHAR_BUDGET = int(os.getenv("AGENT_CONTEXT_TOTAL_CHAR_BUDGET", "10500"))
CONTEXT_SOURCE_CHAR_LIMIT = int(os.getenv("AGENT_CONTEXT_SOURCE_CHAR_LIMIT", "2000"))
STYLE_CONTEXT_CHAR_LIMIT = int(os.getenv("AGENT_STYLE_CONTEXT_CHAR_LIMIT", "1500"))

SOURCE_TYPE_PRIORITY = {
    # Who the user is; small and always relevant.
    "user_card": 130,
    # One dated line per recent session; what "last time" and "on Monday" questions need.
    "recent_sessions": 128,
    # Older parts of this chat; without it the companion forgets beyond the recent window.
    "conversation_summary": 125,
    # The current inline thread contract requires candidate IDs to be present.
    # Keep this above optional memories until thread classification is decoupled.
    "conversation_threads": 120,
    "agent_memories_v3": 110,
    # How the user asked to be talked to; few lines, needed on every reply.
    "how_to_talk": 118,
    # One short doubt to clear up when it fits.
    "open_questions": 117,
    "agent_self_notes": 112,
    "agent_behavior_rules": 115,
    "data_points": 100,
    "friend_style": 90,
    "whatsapp_chat": 85,
    "whatsapp_structured_context": 80,
    "llm_profile": 60,
    "manual_notes": 50,
    "chat_export": 45,
}
SOURCE_TYPE_CHAR_LIMIT = {
    "user_card": 1000,
    "recent_sessions": 1200,
    "conversation_summary": 1900,
    "conversation_threads": 1800,
    # Up to 12 one-line memories with their dates on a "what do you know about me" turn.
    "agent_memories_v3": 2800,
    "agent_self_notes": 1000,
    "agent_behavior_rules": 1400,
    "data_points": 1200,
    "friend_style": STYLE_CONTEXT_CHAR_LIMIT,
    "whatsapp_chat": STYLE_CONTEXT_CHAR_LIMIT,
    "whatsapp_structured_context": 2600,
    "llm_profile": CONTEXT_SOURCE_CHAR_LIMIT,
    "manual_notes": CONTEXT_SOURCE_CHAR_LIMIT,
    "chat_export": CONTEXT_SOURCE_CHAR_LIMIT,
}
MIN_USEFUL_SOURCE_CHARS = 220


@dataclass(frozen=True)
class BudgetedContextSource:
    source: dict[str, Any]
    content: str
    priority: int
    original_index: int
    original_chars: int
    included_chars: int
    truncated: bool


def budget_context_sources(
    context_sources: list[dict[str, Any]] | None,
    *,
    total_budget: int = CONTEXT_TOTAL_CHAR_BUDGET,
    source_limit: int = CONTEXT_SOURCE_LIMIT,
) -> list[BudgetedContextSource]:
    if not context_sources or total_budget <= 0 or source_limit <= 0:
        return []

    ranked = sorted(
        enumerate(context_sources),
        key=lambda item: (
            _source_priority(item[1]),
            -item[0],
        ),
        reverse=True,
    )
    remaining = total_budget
    selected: list[BudgetedContextSource] = []
    for original_index, source in ranked:
        if len(selected) >= source_limit or remaining <= 0:
            break
        source_type = str(source.get("source_type") or "context")
        raw_content = normalize_context_text(str(source.get("content") or ""))
        if not raw_content:
            continue
        allowed = min(remaining, _source_char_limit(source_type))
        if allowed < MIN_USEFUL_SOURCE_CHARS and selected:
            continue
        content = truncate_for_context(raw_content, allowed)
        used = len(content)
        if used <= 0:
            continue
        selected.append(
            BudgetedContextSource(
                source=source,
                content=content,
                priority=_source_priority(source),
                original_index=original_index,
                original_chars=len(raw_content),
                included_chars=used,
                truncated=used < len(raw_content),
            )
        )
        remaining -= used

    selected.sort(key=lambda item: item.original_index)
    return selected


def truncate_for_context(text: str, limit: int) -> str:
    normalized = normalize_context_text(text)
    if limit <= 0:
        return ""
    if len(normalized) <= limit:
        return normalized
    if limit <= 3:
        return normalized[:limit]
    return normalized[: limit - 3].rstrip() + "..."


def normalize_context_text(text: str) -> str:
    return " ".join(text.split())


def _source_priority(source: dict[str, Any]) -> int:
    source_type = str(source.get("source_type") or "context")
    priority = SOURCE_TYPE_PRIORITY.get(source_type, 10)
    metadata = source.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("selected"):
        priority += 20
    if (
        source_type == "whatsapp_structured_context"
        and isinstance(metadata, dict)
        and bool({"whatsapp", "style"} & set(metadata.get("query_intent") or []))
    ):
        priority += 35
    return priority


def _source_char_limit(source_type: str) -> int:
    return SOURCE_TYPE_CHAR_LIMIT.get(source_type, CONTEXT_SOURCE_CHAR_LIMIT)
