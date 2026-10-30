"""The questions Omi already asked in this chat, with what the user said next, so a question the
user turned down or answered is never asked again in other words."""

from __future__ import annotations

from typing import Any

from agent.context_engine.policy.asked_questions import asked_question_lines, asked_questions
from storage import get_conversation

ASKED_QUESTIONS_SOURCE_TYPE = "asked_questions"


def asked_question_sources(conversation_id: str, user_id: str | None) -> list[dict[str, Any]]:
    if not user_id:
        return []
    messages = list((get_conversation(conversation_id, user_id) or {}).get("messages") or [])
    asked = asked_questions(messages)
    if not asked:
        return []
    return [
        {
            "source_type": ASKED_QUESTIONS_SOURCE_TYPE,
            "title": "Questions you already asked here",
            "content": "\n".join(
                [
                    "Questions you asked in this chat, newest last, each with what the user said right after:",
                    *asked_question_lines(asked),
                    "A question they answered is done; one they turned down, called pointless or did not "
                    "answer is closed. Do not ask a listed question again in any words: build on their "
                    "answer, or bring something new instead.",
                ]
            ),
            "metadata": {"question_count": len(asked), "times": [item.times for item in asked]},
        }
    ]


__all__ = ["ASKED_QUESTIONS_SOURCE_TYPE", "asked_question_sources"]
