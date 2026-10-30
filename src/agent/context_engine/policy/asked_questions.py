"""Facts about the questions Omi asked in this chat: how often, and what the user said right after.

Code computes the facts; the model judges what they mean (an answer, a brush-off, a refusal). Seen
live: "kya kar rahe ho abhi?" asked five times in twenty minutes, after the user answered around it
and after "do not ask stupid questions". Nothing told the reply model, or the request checker, that
the question had already been asked and turned down.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agent.shared.clock import utc_now
from agent.shared.timeline import current_session_start, humanize_gap, parse_time

from .freshness import _normalize, _questions, _same_question

# Recent questions worth listing; older ones in the session have usually moved on.
ASKED_QUESTION_LIMIT = 6
_USER_SAID_CHARS = 160


@dataclass(frozen=True)
class AskedQuestion:
    question: str
    # One entry per time it was asked, oldest first: when, and the user's next message (None when
    # nothing came after it yet).
    asked_ago: list[str] = field(default_factory=list)
    user_said: list[str | None] = field(default_factory=list)

    @property
    def times(self) -> int:
        return len(self.asked_ago)


def asked_questions(messages: list[dict[str, Any]], *, now: datetime | None = None, limit: int = ASKED_QUESTION_LIMIT) -> list[AskedQuestion]:
    """Omi's questions in the current session, grouped when they are the same question in other
    words, each with what the user said next. Newest last."""
    current = now or utc_now()
    session = [m for m in messages[current_session_start(messages):] if not m.get("deleted")]
    groups: list[dict[str, Any]] = []
    for index, message in enumerate(session):
        if message.get("role") != "assistant":
            continue
        reply_after = _next_user_text(session, index)
        ago = _ago(message, current)
        for question in _questions(str(message.get("content") or "")):
            normalized = _normalize(question)
            group = next((g for g in groups if _same_question(normalized, g["normalized"])), None)
            if group is None:
                group = {"question": question, "normalized": normalized, "asked_ago": [], "user_said": []}
                groups.append(group)
            else:
                groups.remove(group)
                groups.append(group)  # newest ask last
            group["asked_ago"].append(ago)
            group["user_said"].append(reply_after)
    return [
        AskedQuestion(group["question"], group["asked_ago"], group["user_said"])
        for group in groups[-limit:]
    ]


def asked_question_lines(asked: list[AskedQuestion]) -> list[str]:
    """One line per question: how often it was asked and what the user said each time."""
    lines = []
    for item in asked:
        said = " / ".join(f'"{text}"' if text else "nothing yet" for text in item.user_said)
        times = f"asked {item.times} times: " if item.times > 1 else "asked "
        lines.append(f'- "{item.question}" ({times}{", ".join(item.asked_ago)}) -> they said: {said}')
    return lines


def _next_user_text(session: list[dict[str, Any]], index: int) -> str | None:
    for later in session[index + 1 :]:
        if later.get("role") == "assistant":
            return None
        if later.get("role") == "user":
            text = " ".join(str(later.get("content") or "").split())
            return text[:_USER_SAID_CHARS] if text else None
    return None


def _ago(message: dict[str, Any], now: datetime) -> str:
    sent = parse_time(message.get("created_at"))
    if sent is None:
        return "earlier"
    gap = now - sent
    return "just now" if gap.total_seconds() < 60 else f"{humanize_gap(gap)} ago"


__all__ = ["ASKED_QUESTION_LIMIT", "AskedQuestion", "asked_question_lines", "asked_questions"]
