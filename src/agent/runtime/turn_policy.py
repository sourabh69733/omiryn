from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.context_engine.turn_state import active_turn_state, is_confirmation_to_pending_turn
from agent.context_engine.utils import normalized_memory_text


@dataclass(frozen=True)
class DirectTurnReply:
    reply: str
    reason: str
    confidence: float
    quality: str = "simple_acknowledgement"


ACKNOWLEDGEMENT_TOKENS = {
    "acha",
    "achha",
    "accha",
    "alright",
    "baba",
    "baat",
    "cool",
    "done",
    "fine",
    "good",
    "great",
    "ha",
    "haan",
    "hai",
    "han",
    "h",
    "koi",
    "nahi",
    "nice",
    "no",
    "ok",
    "okay",
    "sahi",
    "sure",
    "thank",
    "thanks",
    "theek",
    "thik",
    "thx",
    "ty",
}

REQUEST_OR_CONTENT_TOKENS = {
    "about",
    "advice",
    "bata",
    "batao",
    "chat",
    "continue",
    "kaise",
    "karu",
    "kya",
    "message",
    "messages",
    "story",
    "suggest",
    "tell",
    "what",
    "why",
}
SINGLE_TOKEN_ACCEPTANCE_ACKS = {"ok", "okay", "sure", "cool", "done", "fine"}


def direct_turn_reply(user_text: str, messages: list[dict[str, Any]]) -> DirectTurnReply | None:
    if "?" in user_text:
        return None
    normalized = normalized_memory_text(user_text)
    if not normalized:
        return None
    if is_confirmation_to_pending_turn(user_text, active_turn_state(messages[:-1])):
        return None
    if _is_thanks(normalized):
        return DirectTurnReply(reply="welcome", reason="gratitude_acknowledgement", confidence=0.95)
    if _is_acceptance_acknowledgement(normalized):
        return DirectTurnReply(reply="okay", reason="acceptance_acknowledgement", confidence=0.86)
    return None


def _is_thanks(normalized: str) -> bool:
    words = normalized.split()
    return len(words) <= 4 and (normalized.startswith("thanks") or normalized.startswith("thank you"))


def _is_acceptance_acknowledgement(normalized: str) -> bool:
    words = normalized.split()
    if len(words) > 5:
        return False
    if len(words) == 1 and words[0] not in SINGLE_TOKEN_ACCEPTANCE_ACKS:
        return False
    if any(token in REQUEST_OR_CONTENT_TOKENS for token in words):
        return False
    known_tokens = [token for token in words if token in ACKNOWLEDGEMENT_TOKENS]
    if not known_tokens:
        return False
    unknown_tokens = [token for token in words if token not in ACKNOWLEDGEMENT_TOKENS]
    return not unknown_tokens and len(known_tokens) == len(words)
