from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

from agent.context_engine.turn_understanding.contract import TurnInterpreter, TurnUnderstanding
from agent.context_engine.turn_understanding.legacy_en_hi import LegacyEnglishHindiInterpreter

DEFAULT_TURN_INTERPRETER = "legacy_en_hi"
TURN_INTERPRETER_ENV = "AGENT_TURN_INTERPRETER"

_INTERPRETERS: dict[str, TurnInterpreter] = {
    LegacyEnglishHindiInterpreter.interpreter_id: LegacyEnglishHindiInterpreter(),
}


def interpret_turn(
    *,
    user_text: str,
    history_messages: list[dict[str, Any]],
    pending_turn_state: dict[str, Any] | None = None,
) -> TurnUnderstanding:
    requested = _requested_interpreter()
    interpreter = _INTERPRETERS.get(requested)
    fallback_reason: str | None = None
    if interpreter is None:
        interpreter = _INTERPRETERS[DEFAULT_TURN_INTERPRETER]
        fallback_reason = f"Unknown interpreter '{requested}'; used {DEFAULT_TURN_INTERPRETER}."
    result = interpreter.interpret(
        user_text=user_text,
        history_messages=history_messages,
        pending_turn_state=pending_turn_state,
    )
    return replace(
        result,
        requested_interpreter=requested,
        fallback_reason=fallback_reason,
    )


def _requested_interpreter() -> str:
    configured = os.getenv(TURN_INTERPRETER_ENV, DEFAULT_TURN_INTERPRETER)
    normalized = configured.strip().casefold()
    return normalized or DEFAULT_TURN_INTERPRETER
