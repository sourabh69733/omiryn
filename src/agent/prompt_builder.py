from __future__ import annotations

import os
from typing import Any

from agent.behavior import (
    CompanionBehavior,
    behavior_prompt,
    build_companion_behavior,
    tone_prompt,
)
from agent.prompt_sections import COMPANION_SYSTEM_PROMPT, CONTEXT_USAGE_RULES

CONTEXT_SOURCE_LIMIT = int(os.getenv("AGENT_CONTEXT_SOURCE_LIMIT", "5"))
CONTEXT_SOURCE_CHAR_LIMIT = int(os.getenv("AGENT_CONTEXT_SOURCE_CHAR_LIMIT", "2000"))
STYLE_CONTEXT_CHAR_LIMIT = int(os.getenv("AGENT_STYLE_CONTEXT_CHAR_LIMIT", "1500"))
STYLE_CONTEXT_TYPES = {"whatsapp_chat", "friend_style"}


def build_companion_system_prompt(
    *,
    context_sources: list[dict[str, Any]] | None,
    user_profile: dict[str, Any] | None,
    agent_tone: str = "auto",
    agent_name: str | None = None,
    base_prompt: str = COMPANION_SYSTEM_PROMPT,
) -> str:
    behavior = build_companion_behavior(user_profile, agent_name=agent_name, tone=agent_tone)
    return build_system_prompt(
        base_prompt=base_prompt,
        behavior=behavior,
        user_profile=user_profile,
        context_sources=context_sources,
    )


def build_system_prompt(
    *,
    base_prompt: str,
    behavior: CompanionBehavior,
    user_profile: dict[str, Any] | None,
    context_sources: list[dict[str, Any]] | None,
) -> str:
    sections = [
        base_prompt,
        behavior_prompt(behavior, user_profile),
        tone_prompt(behavior.tone),
    ]
    context_text = context_sources_text(context_sources)
    if context_text:
        sections.extend([CONTEXT_USAGE_RULES, context_text])
    return "\n\n".join(sections)


def context_sources_text(context_sources: list[dict[str, Any]] | None) -> str:
    if not context_sources:
        return ""
    sections = []
    for source in context_sources[:CONTEXT_SOURCE_LIMIT]:
        title = source.get("title") or "Untitled source"
        source_type = source.get("source_type") or "context"
        content_limit = (
            STYLE_CONTEXT_CHAR_LIMIT
            if source_type in STYLE_CONTEXT_TYPES
            else CONTEXT_SOURCE_CHAR_LIMIT
        )
        content = truncate_for_context(str(source.get("content") or ""), content_limit)
        sections.append(f"[{source_type}] {title}\n{content}")
    return "User-provided context sources:\n" + "\n\n".join(sections)


def truncate_for_context(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."
