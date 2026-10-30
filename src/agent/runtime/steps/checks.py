"""Checks on a finished draft, run in order. Each may ask for one rewrite and is best effort: any
failure keeps the draft. Every check is `async (reply, job) -> (reply, trace info or None)`."""

from __future__ import annotations

import os
from typing import Any, Awaitable, Callable

from agent.context_engine.policy.freshness import (
    question_rule_reason,
    rewrite_instruction,
    stale_reply_reason,
    trim_questions,
    without_copied_replies,
    without_repeated_questions,
)
from agent.context_engine.policy.requests import (
    asked_question_requests,
    broken_requests,
    broken_requests_reason,
    recent_user_requests,
    request_check_input,
    request_check_reason,
)
from agent.providers import check_reply_requests

from .job import ReplyJob

Check = Callable[[str, ReplyJob], Awaitable[tuple[str, dict[str, Any] | None]]]


def freshness_check_enabled() -> bool:
    return os.getenv("AGENT_FRESHNESS_CHECK", "true").strip().lower() != "false"


def request_check_enabled() -> bool:
    return request_check_mode() != "false"


def request_check_mode() -> str:
    """auto (default): run the checker only when a code fact says the draft could break a request.
    always: every reply, as before. false: off."""
    value = os.getenv("AGENT_REQUEST_CHECK", "auto").strip().lower()
    if value in {"false", "0", "off"}:
        return "false"
    return "always" if value in {"always", "true"} else "auto"


async def freshen_reply(reply: str, job: ReplyJob) -> tuple[str, dict[str, Any] | None]:
    """One rewrite when the draft breaks the question limit, is stock filler, or repeats itself."""
    if not freshness_check_enabled():
        return reply, None

    def problem(text: str) -> str | None:
        return question_rule_reason(text, job.question_limit) or stale_reply_reason(text, job.previous_replies)

    reason = problem(reply)
    if reason is None:
        return reply, None
    try:
        # The note goes last, where the model follows it best, and the replies the draft copied
        # leave the history so the rewrite cannot copy them again.
        history = without_copied_replies(job.reply_messages, reply)
        note = rewrite_instruction(reply, reason, quote_draft=len(history) == len(job.reply_messages))
        rewritten = await job.rewrite(note, history)
    except Exception as error:
        return reply, {"reason": reason, "rewritten": False, "error": type(error).__name__}
    if not rewritten.strip():
        return reply, {"reason": reason, "rewritten": False}
    trimmed = False
    if question_rule_reason(rewritten, job.question_limit):
        # The model tends to copy the questions in its own history, even when asked not to.
        rewritten = trim_questions(rewritten, job.question_limit)
        trimmed = True
    # Same for a question it already asked: the rewrite often brings it back.
    rewritten = without_repeated_questions(rewritten, job.previous_replies)
    return rewritten, {"reason": reason, "rewritten": True, "questions_trimmed": trimmed, "still_stale": problem(rewritten) is not None}


async def follow_requests(reply: str, job: ReplyJob) -> tuple[str, dict[str, Any] | None]:
    """One rewrite when the draft breaks how the user asked to be talked to: their saved requests,
    what they asked earlier in this session (saved only once the chat goes quiet), and a question
    already asked here that they turned down or answered."""
    recent = recent_user_requests(job.history, job.user_text)
    if not (job.requests or recent) or not request_check_enabled():
        return reply, None
    reason = "always" if request_check_mode() == "always" else request_check_reason(reply, job.requests, recent, job.asked)
    if reason is None:
        return reply, {"checked": False, "skipped": "no_signal"}
    conversation_id = str(job.generation_arguments.get("conversation_id") or "")
    try:
        raw = await check_reply_requests(
            request_check_input(reply, job.requests, recent, job.asked), conversation_id=conversation_id
        )
    except Exception as error:
        return reply, {"checked": False, "error": type(error).__name__}
    broken = broken_requests(raw, [*job.requests, *recent, *asked_question_requests(job.asked)])
    if not broken:
        return reply, {"checked": True, "reason": reason, "broken": []}
    try:
        # Like the freshness rewrite: the replies the draft copied leave the history, so the
        # rewrite cannot copy them back, and a question it already asked is dropped if it returns.
        history = without_copied_replies(job.reply_messages, reply)
        rewritten = await job.rewrite(rewrite_instruction(reply, broken_requests_reason(broken), keep_length=False), history)
    except Exception as error:
        return reply, {"checked": True, "broken": broken, "rewritten": False, "error": type(error).__name__}
    if not rewritten.strip():
        return reply, {"checked": True, "broken": broken, "rewritten": False}
    if question_rule_reason(rewritten, job.question_limit):
        rewritten = trim_questions(rewritten, job.question_limit)
    rewritten = without_repeated_questions(rewritten, job.previous_replies)
    return rewritten, {"checked": True, "reason": reason, "broken": broken, "rewritten": True}


# In order; the name is the key of its result in the turn trace.
REPLY_CHECKS: tuple[tuple[str, Check], ...] = (
    ("freshness", freshen_reply),
    ("request_check", follow_requests),
)

__all__ = ["REPLY_CHECKS", "follow_requests", "freshen_reply", "freshness_check_enabled", "request_check_enabled", "request_check_mode"]
