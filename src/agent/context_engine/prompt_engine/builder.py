from __future__ import annotations

from typing import Any

from agent.context_engine.context_budget import (
    budget_context_sources,
    truncate_for_context,
)
from agent.context_engine.models import ContextQueryIntent, ConversationPlan, TopicState
from agent.context_engine.prompt_engine.models import PromptBehaviorVersion
from agent.context_engine.prompt_engine.modules.behavior import (
    CompanionBehavior,
    behavior_module_prompt,
    build_companion_behavior,
)
from agent.context_engine.prompt_engine.modules.boredom_recovery import boredom_recovery_prompt
from agent.context_engine.prompt_engine.modules.conversation_flow import (
    conversation_flow_prompt,
    conversation_plan_prompt,
)
from agent.context_engine.prompt_engine.modules.data_point_usage import data_point_usage_prompt
from agent.context_engine.prompt_engine.modules.data_point_targets import data_point_targets_prompt
from agent.context_engine.prompt_engine.modules.final_reminder import final_reminder_prompt
from agent.context_engine.prompt_engine.modules.language import language_module_prompt
from agent.context_engine.prompt_engine.modules.memory_usage import memory_usage_prompt
from agent.context_engine.prompt_engine.modules.output_format import output_format_prompt
from agent.context_engine.prompt_engine.modules.safety import safety_module_prompt
from agent.context_engine.prompt_engine.modules.tone import tone_module_prompt
from agent.context_engine.prompt_engine.modules.whatsapp_usage import whatsapp_usage_prompt
from agent.context_engine.prompt_engine.registry import get_prompt_behavior_version
from agent.context_engine.prompt_engine.structure import (
    PromptSection,
    PromptStructureContext,
    structure_prompt_sections,
)


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
        safety_module_prompt(allow_mild_adult_humor=behavior.allow_mild_adult_humor),
    ]
    context_text = context_sources_text(context_sources)
    if context_text:
        sections.extend(
            [
                memory_usage_prompt(prompt_version),
                whatsapp_usage_prompt(context_sources),
                context_text,
            ]
        )
    return "\n\n".join(section for section in sections if section)


def build_companion_system_prompt_v2(
    *,
    context_sources: list[dict[str, Any]] | None,
    user_profile: dict[str, Any] | None,
    agent_tone: str,
    agent_name: str | None,
    prompt_version: PromptBehaviorVersion,
    query_intent: ContextQueryIntent,
    topic_states: list[TopicState],
    conversation_plan: ConversationPlan,
) -> str:
    behavior = build_companion_behavior(
        user_profile,
        agent_name=agent_name,
        tone=agent_tone,
        prompt_version=prompt_version,
    )
    context_text = context_sources_text(context_sources)
    structure_context = _prompt_structure_context(
        context_sources=context_sources,
        query_intent=query_intent,
    )
    sections = _v2_prompt_sections(
        prompt_version=prompt_version,
        behavior=behavior,
        user_profile=user_profile,
        context_sources=context_sources,
        context_text=context_text,
        query_intent=query_intent,
        topic_states=topic_states,
        conversation_plan=conversation_plan,
    )
    return structure_prompt_sections(sections, structure_context).text


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


def _intent_prompt(query_intent: ContextQueryIntent) -> str:
    labels = ", ".join(query_intent.labels) if query_intent.labels else "general_chat"
    entities = ", ".join(query_intent.entities) if query_intent.entities else "none"
    return (
        "Current user intent:\n"
        f"- labels={labels}\n"
        f"- confidence={query_intent.confidence:.2f}\n"
        f"- entities={entities}\n"
        f"- prefer_structured_whatsapp={query_intent.prefer_structured_whatsapp}\n"
        f"- low_information={query_intent.is_low_information}\n"
        "Use this only to decide what context and conversation move are useful; "
        "do not expose these labels to the user."
    )


def _v2_prompt_sections(
    *,
    prompt_version: PromptBehaviorVersion,
    behavior: CompanionBehavior,
    user_profile: dict[str, Any] | None,
    context_sources: list[dict[str, Any]] | None,
    context_text: str,
    query_intent: ContextQueryIntent,
    topic_states: list[TopicState],
    conversation_plan: ConversationPlan,
) -> list[PromptSection]:
    return [
        PromptSection(
            id="base_identity",
            title="Core Identity",
            content=prompt_version.base_prompt,
            position="start",
            priority=100,
            can_skip=False,
        ),
        PromptSection(
            id="prompt_contract",
            title="Prompt Contract",
            content=prompt_version.prompt_contract,
            position="start",
            priority=95,
            can_skip=False,
        ),
        PromptSection(
            id="behavior",
            title="Behavior",
            content=behavior_module_prompt(behavior, user_profile),
            position="start",
            priority=90,
            can_skip=False,
        ),
        PromptSection(
            id="language",
            title="Language",
            content=language_module_prompt(),
            position="start",
            priority=88,
            can_skip=False,
        ),
        PromptSection(
            id="intent",
            title="Current Intent",
            content=_intent_prompt(query_intent),
            position="middle",
            priority=82,
            include_when=lambda context: bool(context.intent_labels),
        ),
        PromptSection(
            id="conversation_plan",
            title="Conversation Plan",
            content=conversation_plan_prompt(conversation_plan, topic_states),
            position="start",
            priority=84,
            can_skip=False,
        ),
        PromptSection(
            id="data_point_usage",
            title="Data Point Usage",
            content=data_point_usage_prompt(conversation_plan),
            position="middle",
            priority=76,
            include_when=lambda context: context.has_data_points,
        ),
        PromptSection(
            id="data_point_targets",
            title="Data Point Targets",
            content=data_point_targets_prompt(prompt_version.data_point_targets),
            position="middle",
            priority=56,
            include_when=lambda context: context.has_data_points or context.is_low_information,
        ),
        PromptSection(
            id="tone",
            title="Tone",
            content=tone_module_prompt(behavior.tone),
            position="middle",
            priority=74,
            can_skip=False,
        ),
        PromptSection(
            id="safety",
            title="Safety",
            content=safety_module_prompt(allow_mild_adult_humor=behavior.allow_mild_adult_humor),
            position="start",
            priority=86,
            can_skip=False,
        ),
        PromptSection(
            id="memory_usage",
            title="Memory Usage",
            content=memory_usage_prompt(prompt_version),
            position="middle",
            priority=64,
            include_when=lambda context: context.has_context,
        ),
        PromptSection(
            id="whatsapp_usage",
            title="WhatsApp Usage",
            content=whatsapp_usage_prompt(context_sources),
            position="middle",
            priority=72,
            include_when=lambda context: context.has_whatsapp_context,
        ),
        PromptSection(
            id="context_sources",
            title="Context Sources",
            content=context_text,
            position="middle",
            priority=80,
            include_when=lambda context: context.has_context,
            char_limit=5600,
        ),
        PromptSection(
            id="boredom_recovery",
            title="Boredom Recovery",
            content=boredom_recovery_prompt(conversation_plan),
            position="middle",
            priority=60,
            include_when=lambda context: context.is_low_information
            or "boredom_complaint" in context.intent_labels,
        ),
        PromptSection(
            id="output_format",
            title="Output Format",
            content=output_format_prompt(),
            position="end",
            priority=95,
            can_skip=False,
        ),
        PromptSection(
            id="final_reminder",
            title="Final Reminder",
            content=final_reminder_prompt(),
            position="end",
            priority=90,
            can_skip=False,
        ),
    ]


def _prompt_structure_context(
    *,
    context_sources: list[dict[str, Any]] | None,
    query_intent: ContextQueryIntent,
) -> PromptStructureContext:
    source_types = {
        str(source.get("source_type") or "context")
        for source in context_sources or []
    }
    return PromptStructureContext(
        intent_labels=frozenset(query_intent.labels),
        source_types=frozenset(source_types),
        has_context=bool(context_sources),
        has_data_points="data_points" in source_types,
        has_whatsapp_context=bool(
            source_types & {"whatsapp_structured_context", "whatsapp_chat", "friend_style"}
        ),
        is_low_information=query_intent.is_low_information,
    )
