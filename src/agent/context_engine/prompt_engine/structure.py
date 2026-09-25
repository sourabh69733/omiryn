"""Orders, enables, and budgets named system-prompt instruction sections."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Callable

from agent.context_engine.assembly.budget import truncate_for_context

PromptIncludeWhen = Callable[["PromptStructureContext"], bool]

# About 6k tokens. At 12000 the fixed sections alone overflowed, silently cutting the tone,
# output-format and memory-usage rules; raise further only with the prompt trimmed.
PROMPT_TOTAL_CHAR_BUDGET = int(os.getenv("AGENT_PROMPT_TOTAL_CHAR_BUDGET", "24000"))
PROMPT_SECTION_CHAR_LIMIT = int(os.getenv("AGENT_PROMPT_SECTION_CHAR_LIMIT", "2600"))

SECTION_MODES: dict[str, str] = {
    "base_identity": "dynamic",
    "prompt_contract": "dynamic",
    "behavior": "dynamic",
    "language": "dynamic",
    "intent": "dynamic",
    "conversation_plan": "dynamic",
    "empathy": "dynamic",
    "data_point_usage": "dynamic",
    "matching_understanding": "dynamic",
    "data_point_targets": "dynamic",
    "tone": "dynamic",
    "safety": "dynamic",
    "memory_usage": "dynamic",
    "whatsapp_usage": "dynamic",
    "context_sources": "dynamic",
    "boredom_recovery": "dynamic",
    "output_format": "dynamic",
    "final_reminder": "dynamic",
}

SECTION_CHAR_LIMITS: dict[str, int] = {
    "base_identity": 2600,
    "prompt_contract": 2200,
    "behavior": 2200,
    "conversation_plan": 2600,
    "empathy": 1500,
    "matching_understanding": 1600,
    # Matches the 7500-char context source budget in assembly/budget.py, plus headings.
    "context_sources": 9800,
    "boredom_recovery": 1200,
    "output_format": 1200,
    "final_reminder": 900,
}

POSITION_ORDER = {"start": 0, "middle": 1, "end": 2}


@dataclass(frozen=True)
class PromptStructureContext:
    intent_labels: frozenset[str]
    source_types: frozenset[str]
    has_context: bool
    has_data_points: bool
    has_whatsapp_context: bool
    is_low_information: bool
    has_emotion_state: bool


@dataclass(frozen=True)
class PromptSection:
    id: str
    title: str
    content: str
    position: str = "middle"
    priority: int = 50
    mode: str | None = None
    can_skip: bool = True
    minimum_content_chars: int = 1
    include_when: PromptIncludeWhen | None = None
    char_limit: int | None = None


@dataclass(frozen=True)
class StructuredPrompt:
    text: str
    included_sections: tuple[PromptSection, ...]
    skipped_sections: tuple[dict[str, str], ...]


def structure_prompt_sections(
    sections: list[PromptSection],
    context: PromptStructureContext,
    *,
    total_budget: int = PROMPT_TOTAL_CHAR_BUDGET,
) -> StructuredPrompt:
    controlled = [_apply_section_control(section) for section in sections if section.content]
    included: list[PromptSection] = []
    skipped: list[dict[str, str]] = []
    for section in controlled:
        should_include, reason = _should_include_section(section, context)
        if should_include:
            included.append(section)
        else:
            skipped.append({"id": section.id, "reason": reason})

    ordered = sorted(
        included,
        key=lambda section: (
            POSITION_ORDER.get(section.position, POSITION_ORDER["middle"]),
            -section.priority,
        ),
    )
    budgeted = _budget_sections(ordered, skipped, total_budget)
    return StructuredPrompt(
        text="\n\n".join(_render_section(section) for section in budgeted),
        included_sections=tuple(budgeted),
        skipped_sections=tuple(skipped),
    )


def _apply_section_control(section: PromptSection) -> PromptSection:
    configured_mode = _section_mode_overrides().get(section.id)
    mode = configured_mode or section.mode or SECTION_MODES.get(section.id, "dynamic")
    return replace(section, mode=mode)


def _should_include_section(
    section: PromptSection,
    context: PromptStructureContext,
) -> tuple[bool, str]:
    if section.mode == "off":
        return False, "Disabled by prompt section control."
    if section.mode == "always":
        return True, "Always included."
    if section.include_when:
        return section.include_when(context), "Dynamic condition did not match."
    return True, "Included by default dynamic rule."


def _budget_sections(
    sections: list[PromptSection],
    skipped: list[dict[str, str]],
    total_budget: int,
) -> list[PromptSection]:
    if total_budget <= 0:
        return []
    indexed = list(enumerate(sections))
    mandatory = [(index, section) for index, section in indexed if not section.can_skip]
    optional = [(index, section) for index, section in indexed if section.can_skip]
    separator_chars = max(0, len(mandatory) - 1) * len("\n\n")
    remaining = max(0, total_budget - separator_chars)
    selected: list[tuple[int, PromptSection]] = []

    for position, (index, section) in enumerate(mandatory):
        future_minimum = sum(_minimum_rendered_chars(item) for _, item in mandatory[position + 1 :])
        allowed = max(0, remaining - future_minimum)
        fitted = _fit_section(section, allowed)
        if fitted is None:
            skipped.append(
                {"id": section.id, "reason": "Required section could not fit prompt budget."}
            )
            continue
        selected.append((index, fitted))
        remaining -= len(_render_section(fitted))

    for index, section in optional:
        separator = len("\n\n") if selected else 0
        fitted = _fit_section(section, max(0, remaining - separator))
        if fitted is None:
            skipped.append({"id": section.id, "reason": "Dropped by prompt budget."})
            continue
        selected.append((index, fitted))
        remaining -= separator + len(_render_section(fitted))

    selected.sort(key=lambda item: item[0])
    budgeted = [section for _, section in selected]
    while (
        budgeted
        and len("\n\n".join(_render_section(section) for section in budgeted)) > total_budget
    ):
        removable = next((section for section in reversed(budgeted) if section.can_skip), None)
        if removable is None:
            break
        budgeted.remove(removable)
        skipped.append({"id": removable.id, "reason": "Dropped by final rendered prompt budget."})
    return budgeted


def _minimum_rendered_chars(section: PromptSection) -> int:
    minimum_content = min(len(section.content), max(1, section.minimum_content_chars))
    return len(_section_heading(section)) + 1 + minimum_content


def _fit_section(section: PromptSection, available: int) -> PromptSection | None:
    section_limit = section.char_limit or SECTION_CHAR_LIMITS.get(
        section.id,
        PROMPT_SECTION_CHAR_LIMIT,
    )
    limit = min(available, section_limit)
    heading_cost = len(_section_heading(section)) + 1
    if limit <= heading_cost:
        return None
    content = truncate_for_context(section.content, limit - heading_cost)
    if not content:
        return None
    fitted = replace(section, content=content)
    return fitted if len(_render_section(fitted)) <= limit else None


def _render_section(section: PromptSection) -> str:
    return f"{_section_heading(section)}\n{section.content}".strip()


def _section_heading(section: PromptSection) -> str:
    return f"## {section.title}"


def _section_mode_overrides() -> dict[str, str]:
    raw = os.getenv("AGENT_PROMPT_SECTION_MODES", "").strip()
    if not raw:
        return {}
    overrides: dict[str, str] = {}
    for item in raw.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        mode = value.strip().lower()
        if mode in {"always", "dynamic", "off"}:
            overrides[key.strip()] = mode
    return overrides
