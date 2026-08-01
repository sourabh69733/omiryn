from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from agent.context_engine.models import ContextQueryIntent, ConversationalStance, EmotionState


@dataclass(frozen=True)
class LanguageProfile:
    """Script observations only; scripts must not be treated as language identity."""

    scripts: tuple[str, ...] = ()
    primary_script: str | None = None
    script_counts: tuple[tuple[str, int], ...] = ()
    is_mixed_script: bool = False
    has_letters: bool = False


@dataclass(frozen=True)
class TurnUnderstanding:
    """Language-neutral decisions consumed by the v3 conversation planner."""

    intent: ContextQueryIntent
    emotion: EmotionState
    stance: ConversationalStance
    language_profile: LanguageProfile
    interpreter_id: str
    interpreter_version: str
    requested_interpreter: str
    fallback_reason: str | None = None


class TurnInterpreter(Protocol):
    interpreter_id: str
    version: str

    def interpret(
        self,
        *,
        user_text: str,
        history_messages: list[dict[str, Any]],
        pending_turn_state: dict[str, Any] | None = None,
    ) -> TurnUnderstanding:
        ...
