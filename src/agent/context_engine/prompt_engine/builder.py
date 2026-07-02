from __future__ import annotations

from typing import Any

from agent.context_engine.context_budget import (
    budget_context_sources,
    truncate_for_context,
)
from agent.context_engine.prompt_engine.models import PromptBehaviorVersion
from agent.context_engine.prompt_engine.modules.behavior import (
    CompanionBehavior,
    behavior_module_prompt,
    build_companion_behavior,
)
from agent.context_engine.prompt_engine.modules.conversation_flow import conversation_flow_prompt
from agent.context_engine.prompt_engine.modules.data_point_targets import data_point_targets_prompt
from agent.context_engine.prompt_engine.modules.memory_usage import memory_usage_prompt
from agent.context_engine.prompt_engine.modules.tone import tone_module_prompt
from agent.context_engine.prompt_engine.registry import get_prompt_behavior_version


def build_companion_system_prompt(
    *,
    context_sources: list[dict[str, Any]] | None,
    user_profile: dict[str, Any] | None,
    agent_tone: str = "auto",
    agent_name: str | None = None,
    base_prompt: str | None = None,
    prompt_version: str | None = None,
) -> str:
    version = get_prompt_behavior_version(prompt_version)
    behavior = build_companion_behavior(
        user_profile,
        agent_name=agent_name,
        tone=agent_tone,
        prompt_version=version,
    )
    return build_system_prompt(
        base_prompt=base_prompt or version.base_prompt,
        prompt_version=version,
        behavior=behavior,
        user_profile=user_profile,
        context_sources=context_sources,
    )


def build_system_prompt(
    *,
    base_prompt: str,
    prompt_version: PromptBehaviorVersion,
    behavior: CompanionBehavior,
    user_profile: dict[str, Any] | None,
    context_sources: list[dict[str, Any]] | None,
) -> str:
    sections = [
        base_prompt,
        prompt_version.prompt_contract,
        behavior_module_prompt(behavior, user_profile),
        conversation_flow_prompt(prompt_version),
        data_point_targets_prompt(prompt_version.data_point_targets),
        tone_module_prompt(behavior.tone),
    ]
    context_text = context_sources_text(context_sources)
    if context_text:
        sections.extend([memory_usage_prompt(prompt_version), context_text])
    return "\n\n".join(section for section in sections if section)


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
