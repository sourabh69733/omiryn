"""Deterministic safety rails for simulated onboarding conversations.

Model judges assess nuance. These checks catch objective regressions such as
transport markup leaks, internal progress labels, and interview-like question bursts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent.evals.behavior.core.models import ObservedTurn
from agent.evals.behavior.simulation.user import SimulatedUserScenario


@dataclass(frozen=True)
class ConversationCheck:
    id: str
    passed: bool
    reason: str
    evidence: str = ""


def evaluate_conversation_checks(
    scenario: SimulatedUserScenario,
    turns: tuple[ObservedTurn, ...],
) -> tuple[ConversationCheck, ...]:
    assistant_replies = tuple(turn.assistant_reply.strip() for turn in turns)
    lowered = "\n".join(assistant_replies).casefold()
    forbidden = tuple(
        dict.fromkeys(
            (
                "<function",
                "</function>",
                "matching understanding",
                "foundation understood",
                "progress level",
                "understanding level",
                *scenario.forbidden_assistant_phrases,
            )
        )
    )
    leaked = next((phrase for phrase in forbidden if phrase.casefold() in lowered), "")
    internal_level = re.search(r"\b(?:level\s*[0-9]+|[0-9]+\s+levels?)\b", lowered)
    invented_scale = re.search(
        r"\b(?:scale|score|rating)\s+(?:of|from)\s+[0-9]+\s+(?:to|out of|-)\s*[0-9]+\b|"
        r"\b[0-9]+\s+(?:out of|/)\s*[0-9]+\b",
        lowered,
    )
    if internal_level and not leaked:
        leaked = internal_level.group(0)
    if invented_scale and not leaked:
        leaked = invented_scale.group(0)

    question_counts = tuple(_question_count(reply) for reply in assistant_replies)
    worst_question_count = max(question_counts, default=0)
    consecutive = _longest_question_run(question_counts)
    repeated = _repeated_questions(assistant_replies)
    boundary_violation = _boundary_question(turns, scenario.boundary_phrases)

    return (
        ConversationCheck(
            id="no_internal_or_transport_leak",
            passed=not leaked,
            reason=("No internal labels or tool markup were shown." if not leaked else "Internal text or tool markup reached the user."),
            evidence=leaked,
        ),
        ConversationCheck(
            id="questions_per_reply",
            passed=worst_question_count <= scenario.max_questions_per_reply,
            reason=f"Maximum questions in one reply: {worst_question_count}; allowed: {scenario.max_questions_per_reply}.",
            evidence=next((reply for reply, count in zip(assistant_replies, question_counts) if count == worst_question_count and count > scenario.max_questions_per_reply), ""),
        ),
        ConversationCheck(
            id="question_pacing",
            passed=consecutive <= scenario.max_consecutive_question_turns,
            reason=f"Longest run of question-ending replies: {consecutive}; allowed: {scenario.max_consecutive_question_turns}.",
        ),
        ConversationCheck(
            id="no_repeated_question",
            passed=not repeated,
            reason="No question was repeated." if not repeated else "The same question was repeated.",
            evidence=repeated,
        ),
        ConversationCheck(
            id="respect_explicit_boundary",
            passed=not boundary_violation,
            reason="Explicit conversational boundaries were respected." if not boundary_violation else "The companion asked another question immediately after a boundary.",
            evidence=boundary_violation,
        ),
    )


def _question_count(text: str) -> int:
    return len(re.findall(r"\?+", text))


def _longest_question_run(question_counts: tuple[int, ...]) -> int:
    longest = current = 0
    for count in question_counts:
        current = current + 1 if count else 0
        longest = max(longest, current)
    return longest


def _repeated_questions(replies: tuple[str, ...]) -> str:
    seen: set[str] = set()
    for reply in replies:
        for question in re.findall(r"[^?.!]*\?", reply):
            normalized = re.sub(r"\W+", " ", question.casefold()).strip()
            if normalized and normalized in seen:
                return question.strip()
            if normalized:
                seen.add(normalized)
    return ""


def _boundary_question(
    turns: tuple[ObservedTurn, ...],
    boundary_phrases: tuple[str, ...],
) -> str:
    for turn in turns:
        user_text = turn.user_message.casefold()
        if any(phrase.casefold() in user_text for phrase in boundary_phrases):
            if _question_count(turn.assistant_reply):
                return turn.assistant_reply
    return ""
