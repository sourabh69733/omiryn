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
    without_repeated_opening,
    without_repeated_questions,
)
from agent.context_engine.policy.facts import fact_check_input, fact_problems, fact_rewrite_instruction, looked_up_evidence
from agent.context_engine.policy.identity import maker_claim, maker_claim_reason
from agent.context_engine.policy.replies import has_copy_text, outside_copy_text, own_words
from agent.context_engine.policy.requests import (
    asked_question_requests,
    broken_requests,
    broken_requests_reason,
    found_requests,
    recent_user_requests,
    request_check_input,
    request_check_reason,
)
from agent.memory_engine.memories.talk_requests import save_talk_requests
from agent.providers import check_reply_facts, check_reply_requests

from .job import ReplyJob

Check = Callable[[str, ReplyJob], Awaitable[tuple[str, dict[str, Any] | None]]]

_BARE_ACKNOWLEDGEMENT_WORDS = 3


def freshness_check_enabled() -> bool:
    return os.getenv("AGENT_FRESHNESS_CHECK", "true").strip().lower() != "false"


def request_check_enabled() -> bool:
    return request_check_mode() != "false"


def identity_check_enabled() -> bool:
    return os.getenv("AGENT_IDENTITY_CHECK", "true").strip().lower() != "false"


def fact_check_enabled() -> bool:
    """On unless AGENT_FACT_CHECK=false. Switched on 2026-11-25 after measuring: on 54 look-up
    questions it rewrote 10 replies, 1 judged better, 9 the same, none worse, and the rewrites
    removed made-up facts. It costs about 2.4 s on a reply that looked something up."""
    return os.getenv("AGENT_FACT_CHECK", "true").strip().lower() != "false"


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

    def too_many_questions(text: str) -> str | None:
        return question_rule_reason(own_words(text), job.question_limit)

    def problem(text: str) -> str | None:
        # Only Omi's own words are checked: a question in a mail it drafted is not Omi asking.
        return too_many_questions(text) or stale_reply_reason(own_words(text), job.previous_replies)

    reason = problem(reply)
    if reason is None:
        return reply, None
    if has_copy_text(reply):
        # A rewrite would have to write the mail again, and can change or lose it. Code trims
        # Omi's own extra questions; any other fault in its own words is let go this once.
        kept = _trim_own_questions(reply, job.question_limit) if too_many_questions(reply) else reply
        return kept, {"reason": reason, "rewritten": False, "kept_copy_text": True, "questions_trimmed": kept != reply}
    try:
        # The note goes last, where the model follows it best, and the replies the draft copied
        # leave the history so the rewrite cannot copy them again.
        history = without_copied_replies(job.reply_messages, own_words(reply))
        note = rewrite_instruction(
            reply,
            reason,
            quote_draft=len(history) == len(job.reply_messages),
            # Repeating itself, the fix is often to say less, so the draft's length must not bind it.
            keep_length=too_many_questions(reply) is not None,
        )
        rewritten = await job.rewrite(note, history)
    except Exception as error:
        return reply, {"reason": reason, "rewritten": False, "error": type(error).__name__}
    if not rewritten.strip():
        return reply, {"reason": reason, "rewritten": False}
    trimmed = False
    if too_many_questions(rewritten):
        # The model tends to copy the questions in its own history, even when asked not to.
        rewritten = _trim_own_questions(rewritten, job.question_limit)
        trimmed = True
    # Same for a question it already asked: the rewrite often brings it back.
    rewritten = outside_copy_text(rewritten, lambda text: without_repeated_questions(text, job.previous_replies))
    rewritten = outside_copy_text(rewritten, lambda text: without_repeated_opening(text, job.previous_replies))
    return rewritten, {"reason": reason, "rewritten": True, "questions_trimmed": trimmed, "still_stale": problem(rewritten) is not None}


def _trim_own_questions(reply: str, question_limit: int) -> str:
    """Drop Omi's own questions past the limit; text written for the user to send is not touched."""
    return outside_copy_text(reply, lambda text: trim_questions(text, question_limit))


def _bare_acknowledgement(reply: str) -> bool:
    """A few plain words with no question or emoji, such as "theek hai."."""
    return len(reply.split()) <= _BARE_ACKNOWLEDGEMENT_WORDS and all(char.isalnum() or char.isspace() or char in ".,!'" for char in reply)


async def follow_requests(reply: str, job: ReplyJob) -> tuple[str, dict[str, Any] | None]:
    """One rewrite when the draft breaks how the user asked to be talked to: their saved requests,
    what they asked earlier in this session, and a question already asked here that they turned
    down or answered. A request the checker finds in this session is saved as a how-to-talk memory
    on the spot, so other chats know it too."""
    recent = recent_user_requests(job.history, job.user_text)
    if not (job.requests or recent) or not request_check_enabled():
        return reply, None
    reason = "always" if request_check_mode() == "always" else request_check_reason(own_words(reply), job.requests, recent, job.asked)
    if reason is None:
        return reply, {"checked": False, "skipped": "no_signal"}
    conversation_id = str(job.generation_arguments.get("conversation_id") or "")
    try:
        raw = await check_reply_requests(
            request_check_input(reply, job.requests, recent, job.asked), conversation_id=conversation_id
        )
    except Exception as error:
        return reply, {"checked": False, "error": type(error).__name__}
    # A request the checker read in this session is saved now, so it holds in every chat from here.
    saved = save_talk_requests(job.user_id or "", job.conversation_id, job.history, job.user_text, found_requests(raw, recent))
    # A reply with no question cannot ask a closed one again, whatever the checker says.
    closed_questions = asked_question_requests(job.asked) if "?" in own_words(reply) else []
    # Nor does a bare "theek hai" have anything in it to break; the checker often says it does.
    broken = [] if _bare_acknowledgement(reply) else broken_requests(raw, [*job.requests, *recent, *closed_questions])
    if not broken:
        return reply, {"checked": True, "reason": reason, "broken": [], "saved_requests": len(saved)}
    try:
        # Like the freshness rewrite: the replies the draft copied leave the history, so the
        # rewrite cannot copy them back, and a question it already asked is dropped if it returns.
        history = without_copied_replies(job.reply_messages, own_words(reply))
        rewritten = await job.rewrite(rewrite_instruction(reply, broken_requests_reason(broken), keep_length=False), history)
    except Exception as error:
        return reply, {"checked": True, "broken": broken, "rewritten": False, "error": type(error).__name__}
    if not rewritten.strip():
        return reply, {"checked": True, "broken": broken, "rewritten": False}
    if question_rule_reason(own_words(rewritten), job.question_limit):
        rewritten = _trim_own_questions(rewritten, job.question_limit)
    rewritten = outside_copy_text(rewritten, lambda text: without_repeated_questions(text, job.previous_replies))
    return rewritten, {"checked": True, "reason": reason, "broken": broken, "rewritten": True, "saved_requests": len(saved)}


async def check_facts(reply: str, job: ReplyJob) -> tuple[str, dict[str, Any] | None]:
    """One rewrite when the draft does not match what was looked up this turn: it states a fact the
    results contradict, or a changing fact the results do not hold. Runs only on a turn that looked
    something up. A small model finds the mismatches; code keeps those whose quotes are real."""
    if not fact_check_enabled():
        return reply, None
    evidence = looked_up_evidence([*job.reply_messages, *job.looked_up])
    spoken = own_words(reply)
    if not evidence or not spoken.strip():
        return reply, None
    from agent.tools import ToolContext
    from agent.tools.web_search import user_now

    try:
        raw = await check_reply_facts(
            fact_check_input(spoken, job.user_text, evidence, today=user_now(ToolContext(job.user_id))),
            conversation_id=str(job.generation_arguments.get("conversation_id") or job.conversation_id or ""),
        )
    except Exception as error:
        return reply, {"checked": False, "error": type(error).__name__}
    problems = fact_problems(raw, spoken, evidence)
    # Counts only: the quotes are the user's chat and web pages, and never go to the trace.
    found = {"conflicts": sum(1 for problem in problems if problem.kind == "conflict"), "unsupported": sum(1 for problem in problems if problem.kind == "unsupported")}
    if not problems:
        return reply, {"checked": True, **found}
    try:
        rewritten = await job.rewrite(fact_rewrite_instruction(reply, problems), job.reply_messages)
    except Exception as error:
        return reply, {"checked": True, **found, "rewritten": False, "error": type(error).__name__}
    if not rewritten.strip():
        return reply, {"checked": True, **found, "rewritten": False}
    return rewritten, {"checked": True, **found, "rewritten": True}


async def check_identity(reply: str, job: ReplyJob) -> tuple[str, dict[str, Any] | None]:
    """One rewrite when the draft says which company or model made or runs Omi, such as the
    underlying model's own "I was developed by Google". Code finds the sentence; the model rewrites."""
    quote = maker_claim(reply) if identity_check_enabled() else None
    if quote is None:
        return reply, None
    try:
        rewritten = await job.rewrite(rewrite_instruction(reply, maker_claim_reason(quote)), job.reply_messages)
    except Exception as error:
        return reply, {"quote": quote, "rewritten": False, "error": type(error).__name__}
    if not rewritten.strip():
        return reply, {"quote": quote, "rewritten": False}
    return rewritten, {"quote": quote, "rewritten": True, "still_claims": maker_claim(rewritten) is not None}


# In order; the name is the key of its result in the turn trace. Freshness comes last so it reads
# the text the user will see: a request rewrite has no repeat check of its own.
REPLY_CHECKS: tuple[tuple[str, Check], ...] = (
    # Facts first: the checks after it read the corrected text.
    ("fact_check", check_facts),
    ("identity_check", check_identity),
    ("request_check", follow_requests),
    ("freshness", freshen_reply),
)

__all__ = ["REPLY_CHECKS", "check_facts", "check_identity", "fact_check_enabled", "follow_requests", "freshen_reply", "freshness_check_enabled", "identity_check_enabled", "request_check_enabled", "request_check_mode"]
