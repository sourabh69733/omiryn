from __future__ import annotations

from typing import Any

from agent.context_engine.emotion_engine import detect_emotion_state
from agent.context_engine.query_intent import context_query_intent
from agent.context_engine.stance_engine import analyze_conversational_stance
from agent.context_engine.turn_understanding.contract import TurnUnderstanding
from agent.context_engine.turn_understanding.scripts import detect_language_profile


class LegacyEnglishHindiInterpreter:
    interpreter_id = "legacy_en_hi"
    version = "1"

    def interpret(
        self,
        *,
        user_text: str,
        history_messages: list[dict[str, Any]],
        pending_turn_state: dict[str, Any] | None = None,
    ) -> TurnUnderstanding:
        intent = context_query_intent(
            user_text,
            pending_turn_state=pending_turn_state,
            strict_whatsapp=True,
        )
        planning_messages = [
            *history_messages,
            {"role": "user", "content": user_text},
        ]
        emotion = detect_emotion_state(
            user_text=user_text,
            messages=planning_messages,
            intent=intent,
        )
        stance = analyze_conversational_stance(
            user_text,
            history_messages,
            emotion_state=emotion,
        )
        return TurnUnderstanding(
            intent=intent,
            emotion=emotion,
            stance=stance,
            language_profile=detect_language_profile(user_text),
            interpreter_id=self.interpreter_id,
            interpreter_version=self.version,
            requested_interpreter=self.interpreter_id,
        )
