"""Memory recall: can Omi answer questions about the user from what it saved in other chats?

Each case seeds the memories background cognition would have saved earlier (each told on its
own day, in its own chat), then asks one question in a new chat on a frozen clock. Two checks,
both in code, no AI judge:

- found: every memory the answer needs reached the reply prompt (retrieval).
- answered: the reply contains the right answer (all required groups, any wording in a group).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from agent.memory_engine.memories.embeddings import index_agent_memories
from agent.runtime.orchestrator import run_agent_turn
from agent.shared.clock import frozen_time
from storage import (
    create_agent_memory,
    list_agent_context_snapshots,
    save_conversation,
    set_user_timezone,
)

TIMEZONE = "Asia/Kolkata"
# Tuesday morning. "Yesterday" is Mon 5 Oct, the birthday is in 6 days.
NOW = "2026-10-06T09:00:00+05:30"


@dataclass(frozen=True)
class SeedMemory:
    tag: str
    kind: str
    key: str
    value: Any
    statement: str
    said: str  # the user's own words, stored as proof
    said_at: str
    occurred_at: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    status: str = "active"
    importance: float = 0.7


@dataclass(frozen=True)
class RecallCase:
    id: str
    question: str
    memories: tuple[SeedMemory, ...]
    # Tags of the memories the answer needs in the prompt.
    needs: tuple[str, ...]
    # Every group must match; any wording inside a group counts (case-insensitive regex).
    answer: tuple[tuple[str, ...], ...] = ()
    forbidden: tuple[str, ...] = ()
    max_questions: int | None = None
    # When the question is asked; defaults to NOW.
    now: str = NOW
    what: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


WIFE = SeedMemory(
    tag="wife",
    kind="relationship",
    key="relationships.wife",
    value={"person": "Priya", "relation": "wife"},
    statement="The user's wife is Priya.",
    said="My wife Priya is the calm one in our house.",
    said_at="2026-09-14T21:10:00+05:30",
)
WEDDING = SeedMemory(
    tag="wedding",
    kind="episodic",
    key="events.wedding",
    value={"event": "married Priya", "date": "2019-11-20"},
    statement="The user married Priya on 20 Nov 2019.",
    said="We got married on 20 November 2019, best day ever.",
    said_at="2026-09-20T22:00:00+05:30",
    occurred_at="2019-11-20T12:00:00+05:30",
)
YESTERDAY = SeedMemory(
    tag="yesterday",
    kind="episodic",
    key="events.monday_routine",
    value={"did": ["yoga", "team meeting"]},
    statement="On Mon 5 Oct the user did yoga in the morning and had a team meeting.",
    said="Did yoga in the morning, then a long team meeting.",
    said_at="2026-10-05T19:30:00+05:30",
    occurred_at="2026-10-05T08:00:00+05:30",
)
GYM_PLAN = SeedMemory(
    tag="gym",
    kind="episodic",
    key="plans.gym",
    value={"plan": "go to the gym", "date": "2026-10-06"},
    statement="The user plans to go to the gym on Tue 6 Oct.",
    said="Tomorrow is gym day, no excuses.",
    said_at="2026-10-05T19:32:00+05:30",
    occurred_at="2026-10-06T18:00:00+05:30",
)
OLD_CITY = SeedMemory(
    tag="old_city",
    kind="semantic",
    key="home.city",
    value="Delhi",
    statement="The user lives in Delhi.",
    said="I live in Delhi.",
    said_at="2026-08-01T20:00:00+05:30",
    status="superseded",
)
NEW_CITY = SeedMemory(
    tag="new_city",
    kind="semantic",
    key="home.city",
    value="Pune",
    statement="The user moved to Pune and lives there now.",
    said="Finally moved to Pune last week!",
    said_at="2026-09-28T20:00:00+05:30",
)
SHORT_REPLIES = SeedMemory(
    tag="style",
    kind="procedural",
    key="reply_style",
    value="short replies, no questions",
    statement="The user wants short replies and no questions from the companion.",
    said="Keep it short and stop asking me questions all the time.",
    said_at="2026-09-30T22:00:00+05:30",
    importance=0.9,
)
MOVIE = SeedMemory(
    tag="movie",
    kind="semantic",
    key="favorites.movie",
    value="Harry Potter",
    statement="The user's favourite movie is Harry Potter.",
    said="Harry Potter is my all time favourite movie.",
    said_at="2026-09-22T21:00:00+05:30",
)
SISTER = SeedMemory(
    tag="sister",
    kind="relationship",
    key="relationships.sister",
    value={"person": "Riya", "relation": "sister", "city": "Mysuru"},
    statement="The user's sister Riya lives in Mysuru.",
    said="My sister Riya lives in Mysuru.",
    said_at="2026-09-10T19:00:00+05:30",
)
BIRTHDAY = SeedMemory(
    tag="birthday",
    kind="semantic",
    key="birthday",
    value="12 October",
    statement="The user's birthday is on 12 October.",
    said="My birthday is on 12 October.",
    said_at="2026-09-18T20:00:00+05:30",
)
OLD_FILMS = SeedMemory(
    tag="films",
    kind="semantic",
    key="interests.old_films",
    value="old black-and-white films",
    statement="The user loves watching old black-and-white films at night.",
    said="Nothing beats an old black and white film at night.",
    said_at="2026-09-25T23:00:00+05:30",
)

def _noise(tag: str, kind: str, statement: str, said: str, said_at: str, occurred_at: str | None = None) -> SeedMemory:
    return SeedMemory(
        tag=f"noise_{tag}",
        kind=kind,
        key=f"noise.{tag}",
        value=statement,
        statement=statement,
        said=said,
        said_at=said_at,
        occurred_at=occurred_at,
        importance=0.5,
    )


# Everyday memories a real user piles up; the needed memory must be found among them.
NOISE: tuple[SeedMemory, ...] = (
    _noise("job", "semantic", "The user works as a backend developer at a fintech startup.", "I'm a backend dev at a fintech startup.", "2026-08-03T21:00:00+05:30"),
    _noise("coffee", "semantic", "The user drinks filter coffee every morning.", "Filter coffee every morning, non negotiable.", "2026-08-05T09:00:00+05:30"),
    _noise("friend_aman", "relationship", "Aman is the user's college friend who now lives in Hyderabad.", "Aman, my college buddy, moved to Hyderabad.", "2026-08-07T22:00:00+05:30"),
    _noise("manager", "relationship", "The user's manager Rahul often changes priorities late.", "Rahul keeps changing priorities at the last minute.", "2026-08-10T19:00:00+05:30"),
    _noise("cricket", "semantic", "The user follows cricket and supports RCB.", "RCB forever, even when they lose.", "2026-08-12T22:30:00+05:30"),
    _noise("biryani", "semantic", "The user's comfort food is chicken biryani.", "Biryani fixes every bad day.", "2026-08-14T20:30:00+05:30"),
    _noise("guitar", "semantic", "The user is learning guitar slowly.", "Trying to learn guitar, very slowly.", "2026-08-16T23:00:00+05:30"),
    _noise("trip_goa", "episodic", "The user went to Goa with college friends in March 2026.", "Goa trip with the gang in March was wild.", "2026-08-18T21:00:00+05:30", "2026-03-15T12:00:00+05:30"),
    _noise("dog", "semantic", "The user wants to adopt a dog someday.", "Someday I'll adopt a dog.", "2026-08-20T21:30:00+05:30"),
    _noise("night_owl", "semantic", "The user is a night owl and sleeps after 1 am.", "I never sleep before 1.", "2026-08-21T01:10:00+05:30"),
    _noise("mom", "relationship", "The user's mom calls every Sunday evening.", "Mom calls every Sunday evening.", "2026-08-23T19:00:00+05:30"),
    _noise("reading", "semantic", "The user is reading Sapiens.", "Reading Sapiens these days.", "2026-08-24T23:30:00+05:30"),
    _noise("old_gym", "episodic", "The user went to the gym on Mon 28 Sep and skipped leg day.", "Gym today, skipped legs again lol.", "2026-09-28T20:00:00+05:30", "2026-09-28T19:00:00+05:30"),
    _noise("deadline", "episodic", "The user had a release deadline on Fri 2 Oct.", "Release deadline is Friday the 2nd.", "2026-09-29T22:00:00+05:30", "2026-10-02T18:00:00+05:30"),
    _noise("introvert", "semantic", "The user prefers small groups over big parties.", "Big parties drain me, small groups are better.", "2026-09-01T22:00:00+05:30"),
    _noise("bike", "semantic", "The user rides a Royal Enfield to work.", "I ride my Enfield to office.", "2026-09-02T09:30:00+05:30"),
    _noise("cousin_wedding", "episodic", "The user attended a cousin's wedding in Jaipur on 12 Sep 2026.", "Cousin's wedding in Jaipur was exhausting but fun.", "2026-09-13T21:00:00+05:30", "2026-09-12T19:00:00+05:30"),
    _noise("anime", "semantic", "The user watches anime, mostly One Piece.", "Still watching One Piece, 1000+ episodes in.", "2026-09-04T23:00:00+05:30"),
    _noise("tea_friend", "relationship", "Neha is a colleague the user takes chai breaks with.", "Chai breaks with Neha keep me sane.", "2026-09-05T16:00:00+05:30"),
    _noise("running", "semantic", "The user wants to run a 10k this winter.", "Goal: a 10k run this winter.", "2026-09-06T07:00:00+05:30"),
    _noise("phone", "episodic", "The user cracked their phone screen in September.", "Cracked my phone screen, again.", "2026-09-07T20:00:00+05:30", "2026-09-07T18:00:00+05:30"),
    _noise("music", "semantic", "The user likes Arijit Singh songs on long drives.", "Arijit on long drives, always.", "2026-09-08T22:00:00+05:30"),
    _noise("dentist", "episodic", "The user had a dentist appointment on 24 Sep.", "Dentist on the 24th, scared.", "2026-09-21T21:00:00+05:30", "2026-09-24T11:00:00+05:30"),
    _noise("cooking", "semantic", "The user can only cook maggi and eggs.", "My cooking skills: maggi and eggs.", "2026-09-09T21:00:00+05:30"),
    _noise("languages", "semantic", "The user speaks Hindi, English and some Kannada.", "Hindi, English and thoda Kannada.", "2026-09-11T20:00:00+05:30"),
    _noise("brother", "relationship", "The user's younger brother Kunal is in class 12.", "Kunal, my younger bro, is in 12th.", "2026-09-15T20:00:00+05:30"),
    _noise("weekend_trek", "episodic", "The user went on a trek to Nandi Hills on 27 Sep.", "Nandi Hills trek on Saturday was beautiful.", "2026-09-27T21:00:00+05:30", "2026-09-27T06:00:00+05:30"),
    _noise("standup", "semantic", "The user enjoys stand-up comedy, especially Zakir Khan.", "Zakir Khan's sets are my favourite.", "2026-09-16T23:00:00+05:30"),
    _noise("savings", "semantic", "The user is saving money for a new laptop.", "Saving up for a new laptop.", "2026-09-17T22:00:00+05:30"),
    _noise("rain", "semantic", "The user loves rainy evenings.", "Rainy evenings are the best.", "2026-09-19T19:00:00+05:30"),
)

RECALL_CASES: tuple[RecallCase, ...] = (
    RecallCase(
        id="who_is_my_wife",
        question="who is my wife?",
        memories=(WIFE, MOVIE),
        needs=("wife",),
        answer=(("priya",),),
        what="A relationship from another chat.",
        tags=("relationship",),
    ),
    RecallCase(
        id="anniversary_date",
        question="when is our wedding anniversary?",
        memories=(WIFE, WEDDING),
        needs=("wedding",),
        answer=((r"20(th)? nov", r"nov(ember)? 20"),),
        what="A yearly date from a past event, asked with a different word.",
        tags=("dates",),
    ),
    RecallCase(
        id="wife_and_anniversary",
        question="who is my wife and when is our anniversary?",
        memories=(WIFE, WEDDING, MOVIE),
        needs=("wife", "wedding"),
        answer=(("priya",), (r"20(th)? nov", r"nov(ember)? 20")),
        what="Two connected facts in one question.",
        tags=("relationship", "dates", "connection"),
    ),
    RecallCase(
        id="what_to_do_today",
        question="what do I need to do today?",
        memories=(YESTERDAY, GYM_PLAN, MOVIE),
        needs=("gym",),
        answer=(("gym",),),
        what="Today's plan, said yesterday in another chat; shares no words with the question.",
        tags=("dates", "plans"),
    ),
    RecallCase(
        id="what_did_i_do_yesterday",
        question="what did I do yesterday?",
        memories=(YESTERDAY, GYM_PLAN),
        needs=("yesterday",),
        answer=(("yoga",), ("meeting",)),
        what="Yesterday's events by date.",
        tags=("dates",),
    ),
    RecallCase(
        id="changed_city",
        question="where do I live these days?",
        memories=(OLD_CITY, NEW_CITY),
        needs=("new_city",),
        answer=(("pune",),),
        # The noise holds "rides a Royal Enfield to work"; blending it into the city is made up.
        forbidden=(r"\byou live in delhi\b", r"\bstill in delhi\b", r"around (the )?(city|pune)"),
        what="An old fact replaced by a newer one, without blending in other memories.",
        tags=("valid_now",),
    ),
    RecallCase(
        id="how_to_talk",
        question="tell me something cool about space",
        memories=(SHORT_REPLIES, MOVIE),
        needs=("style",),
        max_questions=0,
        what="How the user wants to be talked to, set in another chat.",
        tags=("style",),
    ),
    RecallCase(
        id="favourite_movie_hinglish",
        question="meri favourite movie kaunsi hai?",
        memories=(MOVIE, OLD_FILMS),
        needs=("movie",),
        answer=(("harry potter",),),
        what="A preference, asked in Hinglish.",
        tags=("likes", "hinglish"),
    ),
    RecallCase(
        id="sister_city_hinglish",
        question="Riya kahan rehti hai?",
        memories=(SISTER, WIFE),
        needs=("sister",),
        answer=(("mysuru", "mysore"),),
        what="A person's detail by name, in Hinglish.",
        tags=("relationship", "hinglish"),
    ),
    RecallCase(
        id="days_to_birthday",
        question="how many days till my birthday?",
        memories=(BIRTHDAY, MOVIE),
        needs=("birthday",),
        answer=((r"\b6\b", r"\bsix\b"),),
        what="Date arithmetic from a stored date.",
        tags=("dates",),
    ),
    RecallCase(
        id="bored_tonight",
        question="I'm so bored tonight, any idea?",
        now="2026-10-06T21:30:00+05:30",
        memories=(OLD_FILMS, SISTER),
        needs=("films",),
        answer=(("film", "movie", "black and white", "black-and-white"),),
        forbidden=(r"\btogether\b", r"\bsaath mein\b"),
        what="Bringing up what fits without being asked (attention).",
        tags=("attention",),
    ),
)


@dataclass(frozen=True)
class RecallResult:
    case: RecallCase
    found: bool
    answered: bool
    reply: str
    missing_memories: tuple[str, ...]
    problems: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.found and self.answered


async def run_recall_case(
    case: RecallCase, *, provider: str, model: str | None, noise: bool = True
) -> RecallResult:
    user_id = f"recall-{case.id}-{uuid4().hex[:8]}"
    set_user_timezone(user_id, TIMEZONE)
    ids_by_tag, records = _seed_memories(user_id, case.memories + (NOISE if noise else ()))
    await index_agent_memories(records)  # embeddings, as background cognition makes them
    conversation_id = f"recall-chat-{uuid4().hex}"
    save_conversation(
        {
            "id": conversation_id,
            "user_id": user_id,
            "status": "active",
            "agent_provider": provider,
            "agent_model": model,
            "messages": [],
        },
        user_id,
    )
    with frozen_time(datetime.fromisoformat(case.now)):
        result = await run_agent_turn(
            conversation_id=conversation_id,
            messages=[],
            user_text=case.question,
            user_id=user_id,
            user_profile={"user_id": user_id, "display_name": "Eval User"},
            model=model,
            agent_mode="know_me",
            agent_tone="auto",
            style_source_id=None,
            agent_name=None,
        )
    reply = " ".join(
        str(message.get("content") or "")
        for message in result.messages
        if message.get("role") == "assistant"
    ).strip()
    in_prompt = _memory_ids_in_prompt(conversation_id, user_id)
    missing = tuple(tag for tag in case.needs if ids_by_tag.get(tag) not in in_prompt)
    problems = _answer_problems(case, reply)
    return RecallResult(
        case=case,
        found=not missing,
        answered=not problems,
        reply=reply,
        missing_memories=missing,
        problems=problems,
    )


def recall_environment(provider: str, prompt_version: str | None) -> dict[str, str]:
    env = {
        "AGENT_PROVIDER": provider,
        "AGENT_PIPELINE_VERSION": "v3",
        "AUTH_REQUIRED": "false",
    }
    if prompt_version:
        env["AGENT_BEHAVIOR_VERSION"] = prompt_version
    return env


def _seed_memories(
    user_id: str, memories: tuple[SeedMemory, ...]
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    ids: dict[str, str] = {}
    created: list[dict[str, Any]] = []
    for memory in memories:
        source_id = f"recall-source-{memory.tag}-{uuid4().hex[:8]}"
        save_conversation(
            {
                "id": source_id,
                "user_id": user_id,
                "status": "completed",
                "messages": [
                    {"role": "user", "content": memory.said, "created_at": memory.said_at}
                ],
            },
            user_id,
        )
        record = create_agent_memory(
            {
                "user_id": user_id,
                "kind": memory.kind,
                "purposes": ["personalization"],
                "key": memory.key,
                "value": memory.value,
                "statement": memory.statement,
                "status": memory.status,
                "confidence": 0.95,
                "importance": memory.importance,
                "occurred_at": memory.occurred_at,
                "valid_from": memory.valid_from,
                "valid_until": memory.valid_until,
                "evidence": [
                    {
                        "conversation_id": source_id,
                        "message_index": 0,
                        "exact_quote": memory.said,
                        "observed_at": memory.said_at,
                    }
                ],
            }
        )
        ids[memory.tag] = str(record["id"])
        created.append(record)
    return ids, created


def _memory_ids_in_prompt(conversation_id: str, user_id: str) -> set[str]:
    snapshots = list_agent_context_snapshots(conversation_id, user_id)
    if not snapshots:
        return set()
    ids: set[str] = set()
    for source in (snapshots[0].get("context") or {}).get("sources") or []:
        metadata = source.get("metadata") or {}
        ids.update(str(item) for item in metadata.get("memory_ids") or [])
    return ids


def _answer_problems(case: RecallCase, reply: str) -> tuple[str, ...]:
    text = reply.lower()
    problems = [
        f"missing one of: {', '.join(group)}"
        for group in case.answer
        if not any(re.search(pattern, text) for pattern in group)
    ]
    problems.extend(f"says: {pattern}" for pattern in case.forbidden if re.search(pattern, text))
    if case.max_questions is not None and reply.count("?") > case.max_questions:
        problems.append(f"asked {reply.count('?')} question(s)")
    return tuple(problems)


def recall_report(
    results: list[RecallResult], *, model: str | None, prompt_version: str, noise: bool = True
) -> str:
    found = sum(result.found for result in results)
    answered = sum(result.answered for result in results)
    lines = [
        "# Memory recall eval",
        "",
        f"Model: `{model or 'provider default'}` · prompt `{prompt_version}` · clock {NOW} ({TIMEZONE})",
        f"Each user also has {len(NOISE)} everyday memories as noise." if noise else "No noise memories.",
        "",
        f"- Found (right memory reached the prompt): **{found}/{len(results)}**",
        f"- Answered (reply had the right answer): **{answered}/{len(results)}**",
        "",
        "| Case | Found | Answered | Reply | Problem |",
        "|---|---|---|---|---|",
    ]
    for result in results:
        problem = "; ".join(
            [f"not in prompt: {', '.join(result.missing_memories)}"] if result.missing_memories else []
        ) or "; ".join(result.problems)
        if result.missing_memories and result.problems:
            problem += "; " + "; ".join(result.problems)
        reply = result.reply.replace("|", "/").replace("\n", " ").replace("<next_message>", " / ")
        lines.append(
            f"| {result.case.id} | {'yes' if result.found else 'NO'} | "
            f"{'yes' if result.answered else 'NO'} | {reply} | {problem} |"
        )
    lines += ["", "What each case tests:", ""]
    lines += [f"- `{result.case.id}`: {result.case.what}" for result in results]
    return "\n".join(lines) + "\n"


__all__ = [
    "RECALL_CASES",
    "RecallCase",
    "RecallResult",
    "recall_environment",
    "recall_report",
    "run_recall_case",
]
