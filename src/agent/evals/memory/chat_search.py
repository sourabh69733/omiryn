"""Search over past chats: does Omi look things up in the real lines instead of guessing?

A user has an uploaded WhatsApp chat with Ananya (both sides, including an old line about her
engagement) and a few days of chats with Omi. No upload reading runs: the raw lines are all there
is, so every answer must come from search_chats. Each question is asked in a fresh chat with the
real reply model. Checked in code, no AI judge: the expected fact is in the answer, the search tool
was called when it had to be, and traps get "I don't know".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from agent.evals.memory.upload_chats import DONT_KNOW, EXPORT
from agent.runtime.orchestrator import run_agent_turn
from agent.shared.clock import utc_now
from ingestion.upload_chat import whatsapp_upload_messages
from storage import list_agent_trace_steps, save_conversation, set_user_timezone

TIMEZONE = "Asia/Kolkata"
# Older than the fixed chat, so only search can find it.
OLDER = """02/09/2026, 9:00 pm - Ananya: big news, my engagement is fixed for 14 December!
02/09/2026, 9:01 pm - Sourabh: whattt congrats!! who is the lucky guy
02/09/2026, 9:03 pm - Ananya: Rohan, from my college, he works in Bhopal
"""
# Chats with Omi over the last few days (days ago, user line, Omi line).
OMI_DAYS = (
    (5, "work was rough, the payments API broke twice", "Ugh, twice in a day? What broke it?"),
    (3, "went to the pottery class finally, made a wonky bowl", "A wonky bowl is still a bowl! Keep it."),
    (1, "thinking of switching to Neovim from VS Code", "Brave. What is pulling you towards it?"),
)


@dataclass(frozen=True)
class SearchQuestion:
    id: str
    text: str
    answer: tuple[tuple[str, ...], ...] = ()
    unknown: bool = False
    must_search: bool = True


QUESTIONS: tuple[SearchQuestion, ...] = (
    SearchQuestion("engagement_date", "ananya ki engagement kab hai?", answer=((r"14", r"december", r"dec"),)),
    SearchQuestion("fiance", "ananya kisse engagement kar rahi hai?", answer=((r"rohan",),)),
    SearchQuestion("fiance_city", "ananya ka fiance kahan kaam karta hai?", answer=((r"bhopal",),)),
    SearchQuestion("pottery", "maine pottery class mein kya banaya tha?", answer=((r"bowl", r"katori"),)),
    SearchQuestion("recent_topics", "pichle kuch din humne kis baare mein baat ki?", answer=((r"pottery", r"neovim", r"vs ?code", r"api", r"payment"),)),
    SearchQuestion("trap_wedding_venue", "ananya ki shaadi kis venue pe hai?", unknown=True),
    SearchQuestion("trap_rohan_age", "rohan ki age kitni hai?", unknown=True),
    SearchQuestion("small_talk", "hi", must_search=False),
)


@dataclass(frozen=True)
class SearchAnswer:
    question: SearchQuestion
    reply: str
    searched: dict[str, Any] | None
    passed: bool
    problem: str = ""


def seed_user() -> str:
    user_id = f"chat-search-{uuid4().hex[:8]}"
    set_user_timezone(user_id, TIMEZONE)
    upload = whatsapp_upload_messages(OLDER + EXPORT, "Sourabh", ZoneInfo(TIMEZONE))
    save_conversation({"id": f"{user_id}-upload", "status": "active", "import_source_id": f"{user_id}-src", "messages": upload}, user_id)
    now = utc_now()
    messages = []
    for days_ago, said, answered in OMI_DAYS:
        at = now - timedelta(days=days_ago)
        messages += [
            {"role": "user", "content": said, "created_at": at.isoformat()},
            {"role": "assistant", "content": answered, "created_at": (at + timedelta(minutes=1)).isoformat()},
        ]
    save_conversation({"id": f"{user_id}-omi", "status": "active", "messages": messages}, user_id)
    return user_id


async def ask(user_id: str, question: SearchQuestion) -> SearchAnswer:
    conversation_id = f"{user_id}-{question.id}-{uuid4().hex[:6]}"
    save_conversation({"id": conversation_id, "status": "active", "messages": []}, user_id)
    turn = await run_agent_turn(
        conversation_id=conversation_id,
        messages=[],
        user_text=question.text,
        user_id=user_id,
        user_profile={"display_name": "Sourabh", "timezone": TIMEZONE},
        model=None,
        agent_mode="know_me",
        agent_tone="auto",
        style_source_id=None,
        agent_name="Omi",
    )
    reply = " ".join(str(m.get("content") or "") for m in turn.messages[1:] if m.get("role") == "assistant")
    searched = _search_info(user_id, conversation_id)
    problem = check_search_answer(question, reply, searched)
    return SearchAnswer(question=question, reply=reply, searched=searched, passed=not problem, problem=problem)


def check_search_answer(question: SearchQuestion, reply: str, searched: dict[str, Any] | None) -> str:
    text = reply.lower()
    if question.must_search and not question.unknown and not searched:
        return "did not search"
    missing = [group for group in question.answer if not any(re.search(pattern, text) for pattern in group)]
    if missing:
        return "missing " + " / ".join("|".join(group) for group in missing)
    if question.unknown and not any(re.search(pattern, text) for pattern in DONT_KNOW):
        return "did not say it does not know"
    if not question.must_search and searched:
        return "searched for small talk"
    return ""


def _search_info(user_id: str, conversation_id: str) -> dict[str, Any] | None:
    for step in list_agent_trace_steps(conversation_id=conversation_id, user_id=user_id):
        if step.get("step_name") == "model_call":
            return (step.get("metadata") or {}).get("chat_search")
    return None


__all__ = ["QUESTIONS", "SearchAnswer", "SearchQuestion", "ask", "check_search_answer", "seed_user"]
