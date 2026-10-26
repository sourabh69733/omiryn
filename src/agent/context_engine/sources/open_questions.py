"""The oldest thing background cognition was unsure about, for Omi to ask if it fits."""

from __future__ import annotations

from typing import Any

from agent.config import agent_pipeline_config
from agent.shared.timeline import current_session_start
from storage import get_conversation, list_open_questions, mark_open_question_offered

OPEN_QUESTIONS_SOURCE_TYPE = "open_questions"
# Replies in one session that may see the same open question; then it waits for the next session,
# so an unanswered doubt never turns into nagging.
OPEN_QUESTION_REPLIES_PER_SESSION = 3


def open_question_sources(conversation_id: str, user_id: str | None) -> list[dict[str, Any]]:
    """The oldest thing background cognition was unsure about, for the companion to ask if it fits."""
    if not user_id or agent_pipeline_config().memory_contract_version != 3:
        return []
    questions = list_open_questions(user_id)
    if not questions:
        return []
    messages = list((get_conversation(conversation_id, user_id) or {}).get("messages") or [])
    session = f"{conversation_id}:{current_session_start(messages)}"
    question = next(
        (
            item
            for item in questions
            if item["offered_session"] != session
            or item["offered_count"] < OPEN_QUESTION_REPLIES_PER_SESSION
        ),
        None,
    )
    if question is None:
        return []
    mark_open_question_offered(user_id, question["id"], session)
    return [
        {
            "source_type": OPEN_QUESTIONS_SOURCE_TYPE,
            "title": "Something you are unsure about",
            "content": "\n".join(
                [
                    f"You are unsure: {question['text']}",
                    "Ask it in your own words only if it fits naturally right now. Skip it if they are "
                    "upset, busy with something else, or asked for no questions. If this chat already "
                    "answered it, do not ask again.",
                ]
            ),
            "metadata": {"open_question_id": question["id"]},
        }
    ]


__all__ = ["OPEN_QUESTIONS_SOURCE_TYPE", "OPEN_QUESTION_REPLIES_PER_SESSION", "open_question_sources"]
