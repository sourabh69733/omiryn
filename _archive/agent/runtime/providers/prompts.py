from __future__ import annotations

from typing import Any

from agent.context_engine.prompt_engine.builder import (
    build_companion_system_prompt,
    context_sources_text,
    truncate_for_context,
)
from agent.context_engine.prompt_engine.modules.behavior import (
    behavior_module_prompt,
    build_companion_behavior,
)
from agent.context_engine.prompt_engine.modules.identity import agent_persona_for_interest
from agent.context_engine.prompt_engine.modules.tone import tone_module_prompt


def _system_prompt_with_context(
    system_prompt: str,
    context_sources: list[dict[str, Any]] | None,
    agent_mode: str = "know_me",
    agent_tone: str = "auto",
    user_profile: dict[str, Any] | None = None,
    agent_name: str | None = None,
) -> str:
    return build_companion_system_prompt(
        context_sources=context_sources,
        user_profile=user_profile,
        agent_tone=agent_tone,
        agent_name=agent_name,
        base_prompt=system_prompt,
    )

def _agent_persona_prompt(
    user_profile: dict[str, Any] | None,
    agent_name: str | None = None,
) -> str:
    behavior = build_companion_behavior(user_profile, agent_name=agent_name)
    return behavior_module_prompt(behavior, user_profile)

def _agent_persona_for_interest(interested_in: str) -> dict[str, str]:
    return agent_persona_for_interest(interested_in)

def _agent_tone_prompt(agent_tone: str) -> str:
    return tone_module_prompt(agent_tone)

def _context_sources_text(context_sources: list[dict[str, Any]] | None) -> str:
    return context_sources_text(context_sources)

def _truncate_for_context(text: str, limit: int) -> str:
    return truncate_for_context(text, limit)
