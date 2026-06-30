from __future__ import annotations

from typing import Any

from agent.context_engine.behavior import (
    CompanionBehavior,
    behavior_prompt,
    build_companion_behavior,
    tone_prompt,
)
from agent.context_engine.context_budget import (
    budget_context_sources,
    truncate_for_context,
)
from agent.context_engine.prompt_sections import COMPANION_SYSTEM_PROMPT, CONTEXT_USAGE_RULES


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
    for budgeted_source in budget_context_sources(context_sources):
        source = budgeted_source.source
        title = source.get("title") or "Untitled source"
        source_type = source.get("source_type") or "context"
        sections.append(f"[{source_type}] {title}\n{budgeted_source.content}")
    return "User-provided context sources:\n" + "\n\n".join(sections)
