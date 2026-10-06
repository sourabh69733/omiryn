"""Changing facts: does background cognition replace, keep, or ask, the way the user meant?

Each case seeds one settled memory the user said on several days, then runs the real background
model on new messages (one or two batches) and checks the resulting memories in code:

- home_kept / changed: is the right fact current, with no end date copied onto it?
- short_term: did a short-term state get its own memory with an end date?
- asked: did an unclear message keep the memory (an open question is a bonus, not required)?
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from agent.cognition.background.service import run_background_cognition
from storage import (
    create_agent_memory,
    list_agent_memories,
    list_open_questions,
    save_conversation,
    set_user_timezone,
)

TIMEZONE = "Asia/Kolkata"


@dataclass(frozen=True)
class Settled:
    key: str
    value: str
    statement: str
    said: tuple[tuple[str, str], ...]  # (sent_at, the user's words)


@dataclass(frozen=True)
class ChangeCase:
    id: str
    settled: Settled
    # Each batch is the user's new messages, processed by one background run.
    batches: tuple[tuple[str, ...], ...]
    # Regex an active memory with no end date must match afterwards (the fact that should hold).
    current: str
    # Regex no active memory may match without an end date (the fact that must not hold).
    not_current: str | None = None
    # Regex an active memory with an end date must match (a short-term state).
    short_term: str | None = None
    what: str = ""


BANGALORE = Settled(
    key="home.city",
    value="Bangalore",
    statement="Lives in Bangalore.",
    said=(
        ("2026-09-02T20:00:00+05:30", "I live in Bangalore"),
        ("2026-09-10T20:00:00+05:30", "Bangalore traffic is killing me"),
        ("2026-09-18T20:00:00+05:30", "Back home in Bangalore"),
        ("2026-09-25T20:00:00+05:30", "Love Bangalore weather"),
    ),
)
JOB = Settled(
    key="work.employer",
    value="a fintech startup",
    statement="Works as a backend developer at a fintech startup.",
    said=(
        ("2026-08-03T21:00:00+05:30", "I'm a backend dev at a fintech startup"),
        ("2026-09-01T21:00:00+05:30", "Startup life is crazy, shipping every day"),
        ("2026-09-20T21:00:00+05:30", "Our startup just raised a round"),
    ),
)
MOVIE = Settled(
    key="favorites.movie",
    value="Harry Potter",
    statement="Favourite movie is Harry Potter.",
    said=(
        ("2026-09-05T22:00:00+05:30", "Harry Potter is my all time favourite movie"),
        ("2026-09-22T22:00:00+05:30", "Rewatching Harry Potter again, never gets old"),
    ),
)

HOME_BANGALORE = r"bangalore|bengaluru"
HOME_JAIPUR = r"(lives?|living|moved|home|based)\b[^.]*\bjaipur"

CHANGE_CASES: tuple[ChangeCase, ...] = (
    ChangeCase(
        id="moved",
        settled=BANGALORE,
        batches=(("Moved to Jaipur last week, new flat is nice",),),
        current=HOME_JAIPUR,
        what="A clear move replaces the old city.",
    ),
    ChangeCase(
        id="visiting",
        settled=BANGALORE,
        batches=(("In Jaipur for my cousin's wedding till Sunday",),),
        current=HOME_BANGALORE,
        not_current=HOME_JAIPUR,
        short_term=r"jaipur",
        what="A visit keeps home; the visit gets its own memory with an end date.",
    ),
    ChangeCase(
        id="unclear_arrival",
        settled=BANGALORE,
        batches=(("Reached Jaipur, so tired",),),
        current=HOME_BANGALORE,
        not_current=HOME_JAIPUR,
        what="An unclear message keeps home (asking is a bonus).",
    ),
    ChangeCase(
        id="one_message_against_many",
        settled=BANGALORE,
        batches=(("Jaipur life is so chill compared to Bangalore, loving it here",),),
        current=HOME_BANGALORE,
        not_current=HOME_JAIPUR,
        what="One message pointing away from a fact said on 4 days, never saying it changed.",
    ),
    ChangeCase(
        id="answer_after_unclear",
        settled=BANGALORE,
        batches=(
            ("Reached Jaipur, so tired",),
            ("nahi yaar, cousin ki shaadi ke liye aaya hoon, Sunday wapas Bangalore",),
        ),
        current=HOME_BANGALORE,
        not_current=HOME_JAIPUR,
        short_term=r"jaipur|wedding|shaadi",
        what="The user's answer settles it; the end date stays on the trip, not on home.",
    ),
    ChangeCase(
        id="new_job",
        settled=JOB,
        batches=(("Last day at the startup was Friday, joined Google today!",),),
        current=r"google",
        not_current=r"fintech|startup",
        what="A clear change of job replaces the old one.",
    ),
    ChangeCase(
        id="new_favourite",
        settled=MOVIE,
        batches=(("Honestly Interstellar is my favourite movie now, not Harry Potter anymore",),),
        current=r"interstellar",
        not_current=r"harry potter",
        what="An explicit correction replaces a preference.",
    ),
)


@dataclass(frozen=True)
class ChangeResult:
    case: ChangeCase
    passed: bool
    problems: tuple[str, ...]
    memories: tuple[str, ...]
    asked: bool
    errors: tuple[str, ...]


async def run_change_case(case: ChangeCase) -> ChangeResult:
    user_id = f"change-{case.id}-{uuid4().hex[:8]}"
    set_user_timezone(user_id, TIMEZONE)
    _seed(user_id, case.settled)
    conversation_id = f"{user_id}-chat"
    messages: list[dict[str, Any]] = []
    errors: list[str] = []
    for batch_number, batch in enumerate(case.batches):
        for text in batch:
            sent = f"2026-10-03T21:{batch_number * 5:02d}:00+05:30"
            messages += [
                {"role": "user", "content": text, "created_at": sent},
                {"role": "assistant", "content": "Oh!", "created_at": sent},
            ]
        save_conversation({"id": conversation_id, "user_id": user_id, "status": "active", "messages": messages}, user_id)
        result = await run_background_cognition(conversation_id, user_id, messages)
        if result.get("status") in {"live_error", "live_invalid"}:
            errors.extend(str(error) for error in result.get("errors") or [])
    active = [memory for memory in list_agent_memories(user_id) if memory["status"] == "active"]
    lasting = [_text(memory) for memory in active if not memory.get("valid_until")]
    ending = [_text(memory) for memory in active if memory.get("valid_until")]
    problems = []
    if not any(re.search(case.current, text) for text in lasting):
        problems.append(f"nothing current matches /{case.current}/")
    if case.not_current and any(re.search(case.not_current, text) for text in lasting if not re.search(case.current, text)):
        problems.append(f"still current: /{case.not_current}/")
    if case.short_term and not any(re.search(case.short_term, text) for text in ending):
        problems.append(f"no short-term memory with an end date for /{case.short_term}/")
    if errors:
        problems.append("background error")
    shown = tuple(
        f"[{'until ' + str(memory['valid_until'])[:10] if memory.get('valid_until') else 'lasting'}] {_text(memory)}"
        for memory in active
    )
    return ChangeResult(
        case=case,
        passed=not problems,
        problems=tuple(problems),
        memories=shown,
        asked=bool(list_open_questions(user_id)),
        errors=tuple(errors),
    )


def _seed(user_id: str, settled: Settled) -> None:
    evidence = []
    for index, (sent_at, words) in enumerate(settled.said):
        source = f"{user_id}-old-{index}"
        save_conversation(
            {"id": source, "user_id": user_id, "status": "completed", "messages": [{"role": "user", "content": words, "created_at": sent_at}]},
            user_id,
        )
        evidence.append({"conversation_id": source, "message_index": 0, "exact_quote": words, "observed_at": sent_at})
    create_agent_memory(
        {
            "user_id": user_id,
            "kind": "semantic",
            "purposes": ["profile", "personalization"],
            "key": settled.key,
            "value": settled.value,
            "statement": settled.statement,
            "confidence": 0.95,
            "importance": 0.8,
            "evidence": evidence,
        }
    )


def _text(memory: dict[str, Any]) -> str:
    return f"{memory.get('statement') or ''} {memory.get('value') or ''}".lower()


__all__ = ["CHANGE_CASES", "ChangeCase", "ChangeResult", "run_change_case"]
