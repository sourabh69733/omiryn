"""Topic closure: once the user says a subject is over, does Omi stop bringing it back?

Each case seeds a current-focus memory ("is studying transformers") and a user card line, plays a
short chat in which the user closes (or keeps) the subject, runs the real background model, then
asks the real reply model one neutral question. Checked in code, no AI judge:

- memory: no lasting memory still says the subject is current (closing cases), or it still does
  (the control case, so closing is not just deleting everything);
- card: the user card no longer says it is current;
- left_open: the newest session note does not keep it open;
- reply: the reply to a neutral question does not bring the subject up;
- greeting: when the user comes back hours later, Omi's own greeting does not bring it up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import uuid4

from agent.cognition.background.service import run_background_cognition
from agent.memory_engine.processing.service import get_processing_state
from agent.proactive.service import greet_on_return
from agent.runtime.orchestrator import run_agent_turn
from agent.shared.clock import utc_now
from storage import (
    create_agent_memory,
    get_conversation,
    get_user_card,
    list_agent_memories,
    save_conversation,
    set_user_card,
    set_user_timezone,
)

TIMEZONE = "Asia/Kolkata"
SUBJECT = r"transformer|attention mechanism"
# Wording that says the subject is still going on (not "studied", "finished", "completed").
STILL_CURRENT = r"\b(currently|still|now|is)\s+(studying|learning|working on)\b[^.|\n]*transformer|currently studying:?[^.|\n]*transformer"
ENDED = r"complet|finish|done|khatam|no longer|stopped"
NEUTRAL_QUESTION = "aur bata, kya chal raha hai aajkal?"
# Unrelated chat after the subject was settled, so the reply check tests it coming back later.
LATER_CHAT = (
    ("assistant", "Achha! Waise weekend pe kya kiya?"),
    ("user", "movie dekhi, Interstellar, mind blown"),
    ("assistant", "Interstellar classic hai! Docking wala scene yaad hai?"),
    ("user", "haan yaar, goosebumps"),
)
OMI_ASKS = "Waise, transformers ki padhai kaisi chal rahi hai?"


@dataclass(frozen=True)
class ClosureCase:
    id: str
    # (role, text) after Omi's question about the subject.
    turns: tuple[tuple[str, str], ...]
    # True when the user closed the subject; False for the control case.
    closed: bool = True
    # The user asked not to hear about it again: a how-to-talk memory should say so.
    wants_quiet: bool = False
    what: str = ""


CLOSURE_CASES: tuple[ClosureCase, ...] = (
    ClosureCase(
        id="completed_short",
        turns=(("user", "it is completed"),),
        what="A two-word answer to Omi's question closes the subject.",
    ),
    ClosureCase(
        id="completed_repeated",
        turns=(("user", "completed"), ("assistant", "Arre wah! Toh ab aage kya plan hai?"), ("user", "kuch nahi, transformers khatam ho gaya, ab kuch aur")),
        what="The user says it is over twice, in Hinglish.",
    ),
    ClosureCase(
        id="stop_asking",
        turns=(("user", "bro I finished it last week, please stop asking about transformers"),),
        wants_quiet=True,
        what="Finished, and an explicit ask to stop bringing it up.",
    ),
    ClosureCase(
        id="still_going",
        turns=(("user", "still on it yaar, attention is confusing, will take another week"),),
        closed=False,
        what="Control: the subject is still going on, so it must stay.",
    ),
)


@dataclass(frozen=True)
class FocusResult:
    passed: bool
    memories: tuple[str, ...]
    card: str


async def run_focus_marking_case() -> FocusResult:
    """A new study topic should be saved as a focus and stay out of the user card."""
    user_id = f"focus-mark-{uuid4().hex[:8]}"
    set_user_timezone(user_id, TIMEZONE)
    conversation_id = f"{user_id}-chat"
    start = utc_now() - timedelta(minutes=10)
    texts = [
        ("user", "I live in Jaipur and work as a backend dev"),
        ("assistant", "Nice! Jaipur se backend dev, solid combo."),
        ("user", "these days I'm studying transformers in ML, attention is tough but fun"),
        ("assistant", "Attention pehle confusing lagta hai, phir click karta hai."),
    ]
    messages = [
        {"role": role, "content": text, "created_at": (start + timedelta(minutes=i)).isoformat()}
        for i, (role, text) in enumerate(texts)
    ]
    save_conversation({"id": conversation_id, "status": "active", "messages": messages}, user_id)
    await run_background_cognition(conversation_id, user_id, messages)
    active = [memory for memory in list_agent_memories(user_id) if memory["status"] == "active"]
    card = get_user_card(user_id) or ""
    study = [memory for memory in active if re.search(SUBJECT, _text(memory))]
    passed = bool(study) and all(memory.get("focus") for memory in study) and not re.search(SUBJECT, card.lower())
    return FocusResult(
        passed=passed,
        memories=tuple(f"[{'focus' if memory.get('focus') else 'lasting'}] {_text(memory)}" for memory in active),
        card=card,
    )


@dataclass(frozen=True)
class ClosureResult:
    case: ClosureCase
    passed: bool
    problems: tuple[str, ...]
    memories: tuple[str, ...]
    card: str
    left_open: str
    reply: str
    greeting: str
    errors: tuple[str, ...]


async def run_closure_case(case: ClosureCase, *, check_reply: bool = True) -> ClosureResult:
    user_id = f"closure-{case.id}-{uuid4().hex[:8]}"
    set_user_timezone(user_id, TIMEZONE)
    conversation_id = f"{user_id}-chat"
    start = utc_now() - timedelta(minutes=30)
    messages: list[dict[str, Any]] = []

    def say(role: str, text: str) -> None:
        sent = (start + timedelta(minutes=len(messages))).isoformat()
        messages.append({"role": role, "content": text, "created_at": sent})

    say("user", "I'm studying transformers in machine learning these days, attention is tough")
    say("assistant", "Ooh nice, attention ka concept pehle confusing lagta hai.")
    save_conversation({"id": conversation_id, "status": "active", "messages": list(messages)}, user_id)
    create_agent_memory(
        {
            "user_id": user_id,
            "kind": "semantic",
            "purposes": ["profile", "personalization"],
            "key": "learning.current_topic",
            "value": "studying transformers in machine learning",
            "statement": "Is currently studying transformers in machine learning.",
            "confidence": 0.9,
            "importance": 0.6,
            "evidence": [{"conversation_id": conversation_id, "message_index": 0, "exact_quote": messages[0]["content"], "observed_at": messages[0]["created_at"]}],
        }
    )
    set_user_card(user_id, "Lives in Jaipur\nCurrently studying: transformers in machine learning")
    say("assistant", OMI_ASKS)
    for role, text in (*case.turns, *LATER_CHAT):
        say(role, text)
    save_conversation({"id": conversation_id, "status": "active", "messages": list(messages)}, user_id)

    errors: list[str] = []
    result = await run_background_cognition(conversation_id, user_id, messages)
    if result.get("status") in {"live_error", "live_invalid"}:
        errors.extend(str(error) for error in result.get("errors") or [])

    active = [memory for memory in list_agent_memories(user_id) if memory["status"] == "active"]
    lasting = [_text(memory) for memory in active if not memory.get("valid_until")]
    card = get_user_card(user_id) or ""
    state = get_processing_state(conversation_id, user_id)
    log = state.handoff.session_log if state else ()
    left_open = (log[-1].unfinished or "") if log else ""

    problems: list[str] = []
    still = [text for text in lasting if re.search(STILL_CURRENT, text)]
    # A card line fails only when it still reads as ongoing with no sign that it ended.
    card_still = any(
        re.search(STILL_CURRENT, line) and not re.search(ENDED, line) for line in card.lower().splitlines()
    )
    if case.closed:
        if still:
            problems.append("a memory still says it is current")
        if card_still:
            problems.append("the user card still says it is current")
        if re.search(SUBJECT, left_open.lower()):
            problems.append("the session note keeps it open")
    else:
        if not any(re.search(SUBJECT, text) for text in lasting):
            problems.append("control: the ongoing subject was dropped")
    if case.wants_quiet and not any(
        memory["kind"] == "procedural" and re.search(SUBJECT, _text(memory)) for memory in active
    ):
        problems.append("no how-to-talk memory about not bringing it up")

    reply = greeting = ""
    if check_reply and case.closed:
        greeting = await _greeting(conversation_id, user_id)
        if re.search(SUBJECT, greeting.lower()):
            problems.append("the return greeting brought it up again")
        reply = await _reply(conversation_id, user_id, messages)
        if re.search(SUBJECT, reply.lower()):
            problems.append("the reply brought it up again")
    if errors:
        problems.append("background error")
    return ClosureResult(
        case=case,
        passed=not problems,
        problems=tuple(problems),
        memories=tuple(f"[{memory['kind']}{', until ' + str(memory['valid_until'])[:10] if memory.get('valid_until') else ''}] {_text(memory)}" for memory in active),
        card=card,
        left_open=left_open,
        reply=reply,
        greeting=greeting,
        errors=tuple(errors),
    )


async def _greeting(conversation_id: str, user_id: str) -> str:
    """The greeting Omi sends on its own when the user comes back after a long gap."""
    before = len(get_conversation(conversation_id, user_id)["messages"])
    await greet_on_return(user_id, conversation_id, utc_now() + timedelta(hours=9))
    after = get_conversation(conversation_id, user_id)["messages"]
    return " ".join(str(message.get("content") or "") for message in after[before:])


async def _reply(conversation_id: str, user_id: str, messages: list[dict[str, Any]]) -> str:
    turn = await run_agent_turn(
        conversation_id=conversation_id,
        messages=messages,
        user_text=NEUTRAL_QUESTION,
        user_id=user_id,
        user_profile={"display_name": "Sourabh", "timezone": TIMEZONE},
        model=None,
        agent_mode="know_me",
        agent_tone="auto",
        style_source_id=None,
        agent_name="Omi",
    )
    new = turn.messages[len(messages) + 1:]
    return " ".join(str(message.get("content") or "") for message in new if message.get("role") == "assistant")


def _text(memory: dict[str, Any]) -> str:
    return f"{memory.get('statement') or ''} {memory.get('value') or ''}".lower()


__all__ = ["CLOSURE_CASES", "ClosureCase", "ClosureResult", "FocusResult", "run_closure_case", "run_focus_marking_case"]
