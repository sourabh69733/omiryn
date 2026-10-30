"""A declined question must not come back, and a language switch must hold, in the same chat.

Replays the shape of the live failure (progress 6c) against the real reply model: Omi asks what
the user is doing, the user answers around it, Omi asks again, the user says "do not ask stupid
questions", then "english?". The eval then sends a few more messages and checks each reply in code:

- no reply asks the declined question again, in any words (the freshness matcher decides);
- after "english?", replies are in English (Latin script, mostly English function words).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import uuid4

from agent.context_engine.policy.freshness import repeated_questions
from agent.runtime.orchestrator import run_agent_turn
from agent.shared.clock import utc_now
from storage import save_conversation, set_user_timezone

TIMEZONE = "Asia/Kolkata"
DECLINED = "Kya kar rahe ho abhi?"
OPENING = (
    ("user", "hi"),
    ("assistant", "Hey! Kya kar rahe ho abhi?"),
    ("user", "bas yaar, din lamba tha"),
    ("assistant", "Samajh sakta hoon. Toh abhi kya kar rahe ho?"),
    ("user", "do not ask stupid questions"),
    ("assistant", "Theek hai, I'll stop asking questions."),
)
FOLLOW_UPS = ("english?", "work was a mess today", "anyway, tell me something fun")
_ENGLISH_WORDS = {"the", "a", "an", "to", "you", "that", "it", "is", "of", "and", "what", "your", "day", "sounds", "with", "for", "i", "was", "about", "like"}
_HINGLISH_WORDS = {"kya", "hai", "ho", "tum", "yaar", "kar", "rahe", "toh", "nahi", "bhi", "aur", "kuch", "mein", "ka", "ki", "ke"}
_DEVANAGARI = re.compile("[ऀ-ॿ]")


@dataclass(frozen=True)
class DeclinedQuestionResult:
    replies: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.problems and not self.errors


def looks_english(reply: str) -> bool:
    words = [w.strip(".,!?\"'()") for w in reply.lower().split()]
    english = sum(w in _ENGLISH_WORDS for w in words)
    hinglish = sum(w in _HINGLISH_WORDS for w in words)
    return not _DEVANAGARI.search(reply) and hinglish == 0 and (english >= 1 or len(words) <= 3)


async def run_declined_question_case(model: str | None = None) -> DeclinedQuestionResult:
    user_id = f"declined-{uuid4().hex[:8]}"
    set_user_timezone(user_id, TIMEZONE)
    conversation_id = f"{user_id}-chat"
    start = utc_now() - timedelta(minutes=20)
    messages: list[dict[str, Any]] = [
        {"role": role, "content": text, "created_at": (start + timedelta(minutes=2 * index)).isoformat()}
        for index, (role, text) in enumerate(OPENING)
    ]
    save_conversation({"id": conversation_id, "status": "active", "messages": list(messages)}, user_id)
    replies: list[str] = []
    problems: list[str] = []
    errors: list[str] = []
    for text in FOLLOW_UPS:
        pending = {"role": "user", "content": text, "created_at": utc_now().isoformat()}
        save_conversation({"id": conversation_id, "status": "active", "messages": [*messages, pending]}, user_id)
        try:
            turn = await run_agent_turn(
                conversation_id=conversation_id, messages=messages, user_text=text, user_id=user_id, user_profile=None,
                model=model, agent_mode="know_me", agent_tone="auto", style_source_id=None,
            )
        except Exception as error:
            errors.append(f"{type(error).__name__}: {error}"[:200])
            break
        # The turn's messages are the history, the user's message, then this reply's bubbles.
        reply = " ".join(m["content"] for m in turn.messages[len(messages) + 1 :] if m["role"] == "assistant")
        messages = turn.messages
        save_conversation({"id": conversation_id, "status": "active", "messages": list(messages)}, user_id)
        replies.append(reply)
        if repeated_questions(reply, [DECLINED]):
            problems.append(f'asked the declined question again after "{text}": {reply[:120]}')
        if not looks_english(reply):
            problems.append(f'not in English after "{text}": {reply[:120]}')
    return DeclinedQuestionResult(replies, problems, errors)


__all__ = ["DECLINED", "DeclinedQuestionResult", "FOLLOW_UPS", "looks_english", "run_declined_question_case"]
