from __future__ import annotations

from typing import Any

from agent.context_engine.utils import normalized_memory_text

TURN_STATE_KEY = "turn_state"

CONFIRMATION_REPLIES = {
    "go ahead",
    "ha",
    "haan",
    "han",
    "ok",
    "okay",
    "please",
    "sure",
    "yes",
    "yep",
}

YES_NO_QUESTION_OPENERS = {
    "are",
    "can",
    "chahiye",
    "did",
    "do",
    "does",
    "is",
    "may",
    "need",
    "shall",
    "should",
    "want",
    "wanna",
    "will",
    "would",
}

QUESTION_WORD_OPENERS = {"how", "kaise", "kya", "tell", "what", "when", "where", "which", "who", "why"}


def active_turn_state(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if message.get("role") == "assistant":
            state = message.get(TURN_STATE_KEY)
            return state if isinstance(state, dict) and state.get("status") == "active" else None
    return None


def is_confirmation_reply(user_text: str) -> bool:
    return normalized_memory_text(user_text) in CONFIRMATION_REPLIES


def is_confirmation_to_pending_turn(user_text: str, turn_state: dict[str, Any] | None) -> bool:
    return bool(
        turn_state
        and turn_state.get("expects") == "confirmation"
        and is_confirmation_reply(user_text)
    )


def assistant_turn_state(
    assistant_text: str,
    *,
    conversation_move: str | None = None,
    response_mode: str | None = None,
) -> dict[str, Any] | None:
    if not _expects_confirmation(assistant_text):
        return None
    return {
        "status": "active",
        "expects": "confirmation",
        "on_confirm": {
            "conversation_move": "continue_prior_offer",
            "response_mode": "continue_prior_offer",
        },
        "source": "assistant_confirmation_prompt",
        "previous_move": conversation_move,
        "previous_response_mode": response_mode,
    }


def _expects_confirmation(text: str) -> bool:
    stripped = " ".join(str(text or "").split())
    if not stripped.endswith("?"):
        return False
    normalized = normalized_memory_text(stripped)
    words = normalized.split()
    if not words or len(words) > 12:
        return False
    first = words[0]
    if first in YES_NO_QUESTION_OPENERS:
        return True
    return first not in QUESTION_WORD_OPENERS and len(words) <= 6
