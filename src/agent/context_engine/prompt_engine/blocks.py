"""Builds the v4 system prompt: tagged blocks, stable ones first and this turn's facts last.

Rules and facts never mix: who Omi is and the hard rules come first, then what is known about the
user, then this chat, then facts about this turn computed in code, then the goal. Each block has
its own size limit, so one long source cannot push out another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.context_engine.assembly.budget import budget_context_sources
from agent.context_engine.contracts.models import MatchingUnderstanding
from agent.context_engine.prompt_engine.models import PromptBehaviorVersion
from agent.context_engine.prompt_engine.modules.behavior import (
    build_companion_behavior,
    time_awareness_prompt,
)
from agent.context_engine.prompt_engine.modules.identity import voice_prompt
from agent.context_engine.prompt_engine.modules.language import language_module_prompt
from agent.context_engine.prompt_engine.modules.matching_understanding import (
    matching_understanding_prompt,
)
from agent.context_engine.prompt_engine.modules.output_format import output_format_prompt
from agent.context_engine.prompt_engine.modules.safety import safety_module_prompt
from agent.context_engine.prompt_engine.modules.tone import tone_module_prompt
from agent.context_engine.prompt_engine.modules.whatsapp_usage import whatsapp_usage_prompt
from agent.context_engine.prompt_engine.versions.v4 import V4_GOAL

# Where each context source goes. Anything not listed is attached material (imports, styles).
_SOURCE_BLOCKS = {
    "user_card": "about_user",
    "agent_memories_v3": "memories",
    "how_to_talk": "how_to_talk",
    "data_points": "memories",
    "agent_self_notes": "your_notes",
    "conversation_summary": "this_chat",
    "recent_sessions": "this_chat",
    "conversation_threads": "this_chat",
}
BLOCK_CHAR_LIMITS = {
    "omi": 2600,
    "rules": 4200,
    "format": 1400,
    "about_user": 2000,
    "friend_vibe": 3600,
    "memories": 3200,
    "your_notes": 1400,
    "this_chat": 3600,
    "attached": 4000,
    "how_to_talk": 1200,
    "this_turn": 2000,
    "goal": 1200,
}
_CONSTRAINT_FACTS = {
    "no_questions": "They asked you not to ask questions.",
    "no_advice": "They do not want advice.",
    "listen_only": "They want you to listen.",
    "give_space": "They asked for space.",
}


@dataclass(frozen=True)
class TurnFacts:
    """What code knows about this turn; the model decides what to do with it."""

    user_words: int = 0
    user_asked: bool = False
    omi_last_asked: bool = False
    question_streak: int = 0
    constraints: tuple[str, ...] = ()
    earlier_constraints: tuple[str, ...] = ()
    active_topic: str | None = None

    @property
    def no_questions(self) -> bool:
        return self.question_streak >= 2 or "no_questions" in (
            *self.constraints,
            *self.earlier_constraints,
        )


def turn_facts(
    messages: list[dict[str, Any]],
    *,
    question_streak: int,
    constraints: tuple[str, ...] = (),
    earlier_constraints: tuple[str, ...] = (),
    active_topic: str | None = None,
) -> TurnFacts:
    """messages ends with the user's latest message."""
    latest = str(messages[-1].get("content") or "") if messages else ""
    previous = next(
        (message for message in reversed(messages[:-1]) if message.get("role") == "assistant"),
        None,
    )
    return TurnFacts(
        user_words=len(latest.split()),
        user_asked="?" in latest,
        omi_last_asked=previous is not None and "?" in str(previous.get("content") or ""),
        question_streak=question_streak,
        constraints=constraints,
        earlier_constraints=tuple(item for item in earlier_constraints if item not in constraints),
        active_topic=active_topic,
    )


def build_companion_system_prompt_v4(
    *,
    context_sources: list[dict[str, Any]] | None,
    user_profile: dict[str, Any] | None,
    agent_tone: str,
    agent_name: str | None,
    prompt_version: PromptBehaviorVersion,
    matching_understanding: MatchingUnderstanding | None,
    facts: TurnFacts,
    agent_voice: str = "neutral",
) -> str:
    behavior = build_companion_behavior(
        user_profile,
        agent_name=agent_name,
        tone=agent_tone,
        prompt_version=prompt_version,
        voice=agent_voice,
    )
    time_facts, time_rules = _split_time_prompt(time_awareness_prompt(user_profile))
    grouped = _grouped_sources(context_sources)
    attached = grouped.pop("attached", [])
    blocks = [
        ("omi", [
            prompt_version.base_prompt.replace("{name}", behavior.persona_name),
            voice_prompt(behavior.voice),
            tone_module_prompt(agent_tone) if agent_tone not in {"", "auto"} else "",
        ]),
        ("rules", [
            prompt_version.prompt_contract,
            time_rules,
            language_module_prompt(),
            safety_module_prompt(allow_mild_adult_humor=behavior.allow_mild_adult_humor),
        ]),
        ("format", [output_format_prompt()]),
        ("about_user", [_user_basics(user_profile), *grouped.get("about_user", [])]),
        ("friend_vibe", [
            matching_understanding_prompt(matching_understanding) if matching_understanding else "",
        ]),
        ("memories", grouped.get("memories", [])),
        ("your_notes", grouped.get("your_notes", [])),
        ("this_chat", grouped.get("this_chat", [])),
        ("attached", (
            [prompt_version.context_usage_rules, whatsapp_usage_prompt(context_sources), *attached]
            if attached
            else []
        )),
        ("how_to_talk", grouped.get("how_to_talk", [])),
        ("this_turn", [time_facts, _turn_lines(facts)]),
        ("goal", [V4_GOAL]),
    ]
    return "\n\n".join(filter(None, (_block(tag, parts) for tag, parts in blocks)))


def _block(tag: str, parts: list[str]) -> str:
    body = "\n\n".join(part.strip() for part in parts if part and part.strip())
    if not body:
        return ""
    return f"<{tag}>\n{_fit(body, BLOCK_CHAR_LIMITS[tag])}\n</{tag}>"


def _clean_lines(text: str) -> str:
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def _fit(text: str, limit: int) -> str:
    """Cut at a line break within the limit, keeping the block's lines intact."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit("\n", 1)[0]
    return f"{cut}\n..."


def _grouped_sources(context_sources: list[dict[str, Any]] | None) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for budgeted in budget_context_sources(context_sources):
        source_type = str(budgeted.source.get("source_type") or "context")
        block = _SOURCE_BLOCKS.get(source_type, "attached")
        # The budget picks the sources and their size; the text keeps its own lines.
        text = _fit(_clean_lines(str(budgeted.source.get("content") or "")), len(budgeted.content))
        if block == "attached":
            text = f"[{source_type}] {budgeted.source.get('title') or 'Untitled source'}\n{text}"
        grouped.setdefault(block, []).append(text)
    return grouped


def _split_time_prompt(text: str) -> tuple[str, str]:
    """The time prompt mixes this turn's times with standing rules; each goes to its block."""
    lines = text.splitlines()
    rules = [line for line in lines if line.startswith(_TIME_RULE_STARTS)]
    facts = [line for line in lines if line not in rules]
    return "\n".join(facts), "\n".join(f"- {line}" for line in rules)


_TIME_RULE_STARTS = ("Notes like", "Answer when-questions")


def _user_basics(user_profile: dict[str, Any] | None) -> str:
    profile = user_profile or {}
    fields = {
        "name": profile.get("display_name"),
        "gender": profile.get("gender"),
        "location": profile.get("location"),
        "country": profile.get("country"),
        "email": profile.get("email"),
    }
    known = ", ".join(f"{key}={value}" for key, value in fields.items() if value)
    return f"Basics: {known}." if known else ""


def _turn_lines(facts: TurnFacts) -> str:
    lines = []
    asked = ", and it asks something" if facts.user_asked else ""
    words = "1 word" if facts.user_words == 1 else f"{facts.user_words} words"
    lines.append(f"Their latest message: {words}{asked}.")
    lines.append(
        "Your last reply asked them a question."
        if facts.omi_last_asked
        else "Your last reply did not ask a question."
    )
    if facts.question_streak >= 2:
        lines.append(
            f"Your last {facts.question_streak} replies all asked questions: do not ask one now."
        )
    lines.extend(_CONSTRAINT_FACTS[item] for item in facts.constraints if item in _CONSTRAINT_FACTS)
    lines.extend(
        f"A few messages ago: {_CONSTRAINT_FACTS[item][0].lower()}{_CONSTRAINT_FACTS[item][1:]} "
        "This still holds unless they changed it."
        for item in facts.earlier_constraints
        if item in _CONSTRAINT_FACTS
    )
    if facts.active_topic:
        lines.append(f"Current topic in this chat: {facts.active_topic}.")
    return "\n".join(lines)


__all__ = ["BLOCK_CHAR_LIMITS", "TurnFacts", "build_companion_system_prompt_v4", "turn_facts"]
