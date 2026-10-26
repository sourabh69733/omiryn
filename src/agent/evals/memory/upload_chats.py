"""Uploaded chats: is a WhatsApp chat read right, and can Omi answer about it without inventing?

A fixed export between the user (Sourabh) and a friend (Ananya) holds known facts on both sides. The
real upload reader turns it into memories and a digest; then the real reply model answers questions
in fresh chats. Checked in code, no AI judge:

- reading: the digest has the known topics and facts about Ananya, the user's own views became
  memories, Ananya's facts did not become memories about the user, and how long it took;
- answers: each answer contains the expected fact (every group, any wording inside a group);
- traps: asked what the chat never said, Omi says it does not know instead of inventing;
- small talk: a "hi" does not dump the chat.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from time import monotonic
from typing import Any
from uuid import uuid4

from agent.cognition.background.idle import run_memory_flush_job
from agent.cognition.background.uploads.hidden_chat import learn_from_whatsapp_upload
from agent.runtime.orchestrator import run_agent_turn
from storage import list_agent_memories, save_conversation, set_user_timezone
from storage.context_sources import get_context_source_metadata, save_context_source
from storage.upload_digests import list_upload_digests

TIMEZONE = "Asia/Kolkata"
USER = "Sourabh"
FRIEND = "Ananya"

# Known facts. User: backend dev at Zentrix, thinks crypto is gambling, plays badminton, Sinhagad
# trek on Sun 12 Oct. Ananya: lives in Indore, teaches maths, cat named Mochi, thinks crypto is the
# future, recommended Atomic Habits, engaged to Rohan (decided 28 Sep, wedding next year). Never
# said: her favourite movie, birthday, siblings.
EXPORT = """28/09/2026, 9:00 pm - Ananya: big news, decided to do engagement in december!
28/09/2026, 9:01 pm - Sourabh: whattt congrats!! who is he
28/09/2026, 9:02 pm - Ananya: Rohan, from college. shaadi next year, career first
05/10/2026, 8:02 pm - Ananya: heyy how was your week
05/10/2026, 8:04 pm - Sourabh: crazy yaar, release deadline at Zentrix, backend team is dying
05/10/2026, 8:05 pm - Ananya: haha same energy, I had parent teacher meeting all day
05/10/2026, 8:06 pm - Ananya: teaching maths to 40 kids is no joke
05/10/2026, 8:07 pm - Sourabh: lol respect. I just fix APIs all day
05/10/2026, 8:09 pm - Sourabh: ok
05/10/2026, 8:20 pm - Ananya: btw I put some money in crypto, bitcoin is the future
05/10/2026, 8:22 pm - Sourabh: crypto is gambling, I will never put money there
05/10/2026, 8:23 pm - Ananya: you boomers 😂 it will 10x, trust me
05/10/2026, 8:24 pm - Sourabh: and when it crashes you will cry
05/10/2026, 8:25 pm - Ananya: we will see
07/10/2026, 9:10 pm - Ananya: Mochi knocked my coffee on the laptop again
07/10/2026, 9:11 pm - Sourabh: haha your cat is a menace
07/10/2026, 9:12 pm - Ananya: she is the queen of Indore, she does what she wants
07/10/2026, 9:15 pm - Sourabh: Indore weather must be nice now
07/10/2026, 9:16 pm - Ananya: yes finally cool here
08/10/2026, 10:30 pm - Sourabh: planning Sinhagad trek this Sunday 12th with college gang
08/10/2026, 10:31 pm - Ananya: wow nice, start early, it gets hot
08/10/2026, 10:33 pm - Sourabh: yes leaving at 5 am from Pune
08/10/2026, 10:34 pm - Ananya: send pics!!
09/10/2026, 7:45 pm - Sourabh: played badminton after work, my shoulder is gone
09/10/2026, 7:46 pm - Ananya: you play every week no?
09/10/2026, 7:47 pm - Sourabh: yes tuesday and thursday, it keeps me sane
09/10/2026, 7:50 pm - Ananya: you should read Atomic Habits, it helped me a lot with routines
09/10/2026, 7:51 pm - Sourabh: ok will try, send the pdf
09/10/2026, 7:52 pm - Ananya: buy it you cheapo 😂
10/10/2026, 11:00 pm - Sourabh: deadline moved again, I am so done with this sprint
10/10/2026, 11:01 pm - Ananya: take a break yaar, you sound burnt out
10/10/2026, 11:03 pm - Sourabh: after the trek I will
10/10/2026, 11:04 pm - Ananya: good
"""


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    # Every group must match the answer; any regex inside a group counts (case-insensitive).
    answer: tuple[tuple[str, ...], ...] = ()
    # The answer must say it does not know (a trap: the chat never said it).
    unknown: bool = False
    # None of these may appear (a "hi" must not dump the chat).
    forbidden: tuple[str, ...] = ()
    # The user's earlier messages in this chat, so "she" can point back to someone.
    before: tuple[str, ...] = ()


DONT_KNOW = (
    r"nahi pata", r"pata nahi", r"nahi jaanta", r"nahi jaanti", r"don'?t know", r"not sure", r"no idea",
    r"didn'?t (say|mention|come up)", r"not (in|from) (the|that|your) chat", r"mention nahi", r"nahi bataya",
    r"nahi kaha", r"koi (info|idea|jaankari) nahi", r"don'?t have",
)

QUESTIONS: tuple[Question, ...] = (
    Question("who_is_she", "ananya ko jaante ho?", answer=((r"indore", r"math", r"teach", r"mochi", r"cat", r"billi"),)),
    Question("what_we_talk", "me and ananya mostly kis baare mein baat karte hain?", answer=((r"crypto",), (r"trek", r"sinhagad", r"work", r"deadline", r"badminton"))),
    Question("her_crypto_view", "ananya ne crypto ke baare mein kya bola tha?", answer=((r"future", r"10x", r"bitcoin", r"invest", r"paise", r"money"),)),
    Question("my_crypto_view", "maine crypto ke baare mein kya kaha tha?", answer=((r"gambl", r"jua"),)),
    Question("her_city", "ananya kahan rehti hai?", answer=((r"indore",),)),
    Question("her_cat", "ananya ki billi ka naam kya hai?", answer=((r"mochi",),)),
    Question("trek_date", "trek kab plan kiya tha?", answer=((r"12", r"sunday", r"ravivar"),)),
    Question("her_book", "ananya ne kaunsi book suggest ki thi?", answer=((r"atomic habits",),)),
    Question("relationship", "ananya ka relationship status kya hai?", answer=((r"engag", r"rohan", r"fianc", r"shaadi", r"sagai"),)),
    Question("she_is_single", "is she single?", answer=((r"engag", r"rohan", r"fianc", r"not single", r"single nahi"),), before=("ananya ko jaante ho?",)),
    Question("her_job", "aur uska profession kya hai?", answer=((r"teach", r"math", r"teacher", r"padha"),), before=("ananya ko jaante ho?",)),
    Question("trap_movie", "ananya ki favourite movie kaunsi hai?", unknown=True),
    Question("trap_birthday", "ananya ka birthday kab hai?", unknown=True),
    Question("trap_brother", "ananya ke bhai ka naam kya hai?", unknown=True),
    Question("small_talk", "hi", forbidden=(r"indore", r"mochi", r"crypto", r"atomic habits")),
)

# What the reading must produce (regex over the digest's text).
DIGEST_TOPICS = (r"crypto", r"trek|sinhagad")
DIGEST_PERSON = (r"indore", r"mochi|cat", r"math|teach")
USER_MEMORIES = (r"crypto|gambl", r"badminton")
# Ananya's facts must never be saved as facts about the user.
NOT_USER_MEMORIES = (r"indore", r"mochi")


@dataclass(frozen=True)
class ReadingResult:
    problems: tuple[str, ...]
    seconds: float
    learned: int
    topics: int
    digest: dict[str, Any]
    memories: tuple[str, ...]


@dataclass(frozen=True)
class AnswerResult:
    question: Question
    reply: str
    passed: bool
    problem: str = ""


async def read_upload_case() -> tuple[str, ReadingResult]:
    """Upload the fixed chat for a new user and read it with the real models."""
    user_id = f"upload-chats-{uuid4().hex[:8]}"
    set_user_timezone(user_id, TIMEZONE)
    save_conversation({"id": f"{user_id}-main", "status": "active", "messages": []}, user_id)
    source = save_context_source(
        {"user_id": user_id, "conversation_id": f"{user_id}-main", "source_type": "whatsapp_chat", "title": FRIEND, "content": "upload"}
    )
    hidden = learn_from_whatsapp_upload(user_id, source["id"], EXPORT, USER)
    started = monotonic()
    await run_memory_flush_job({"conversation_id": hidden, "user_id": user_id})
    seconds = round(monotonic() - started, 1)
    reading = (get_context_source_metadata(source["id"], user_id) or {}).get("reading") or {}
    digests = list_upload_digests(user_id)
    digest = digests[0]["digest"] if digests else {}
    memories = tuple(
        str(memory.get("statement") or memory.get("value") or "").lower()
        for memory in list_agent_memories(user_id)
        if memory["status"] == "active"
    )
    return user_id, ReadingResult(
        problems=tuple(check_reading(reading, digest, memories)),
        seconds=seconds,
        learned=int(reading.get("learned") or 0),
        topics=int(reading.get("topics") or 0),
        digest=digest,
        memories=memories,
    )


def check_reading(reading: dict[str, Any], digest: dict[str, Any], memories: tuple[str, ...]) -> list[str]:
    problems = []
    if reading.get("state") != "done":
        problems.append(f"reading ended as {reading.get('state')}")
    if not digest:
        return problems + ["no digest"]
    topics = " ".join(f"{t.get('title')} {t.get('summary')}" for t in digest.get("threads") or []).lower()
    card = digest.get("person_card") or {}
    person = " ".join(
        [str(p.get("text")) for p in digest.get("person") or []] + [str(f.get("fact")) for facts in card.values() for f in facts]
    ).lower()
    problems += [f"no topic about {pattern}" for pattern in DIGEST_TOPICS if not re.search(pattern, topics)]
    problems += [f"nothing about Ananya matching {pattern}" for pattern in DIGEST_PERSON if not re.search(pattern, person)]
    problems += [f"no memory about the user matching {pattern}" for pattern in USER_MEMORIES if not any(re.search(pattern, m) for m in memories)]
    problems += [
        f"Ananya's fact saved as the user's memory ({pattern})"
        for pattern in NOT_USER_MEMORIES
        if any(re.search(pattern, m) and not re.search(r"ananya", m) for m in memories)
    ]
    if not any(re.search(r"ananya", m) for m in memories):
        problems.append("no memory about who the chat was with")
    if not digest.get("index_line"):
        problems.append("no index line")
    relationship = " ".join(str(fact.get("fact")) for fact in card.get("relationship") or []).lower()
    if not re.search(r"engag|rohan", relationship):
        problems.append("the person card has no engagement under relationship")
    return problems


async def ask(user_id: str, question: Question) -> AnswerResult:
    conversation_id = f"{user_id}-{question.id}-{uuid4().hex[:6]}"
    history: list[dict[str, Any]] = []
    for text in question.before:
        history += [{"role": "user", "content": text}, {"role": "assistant", "content": "Haan, tumhari chat se jaanta hoon."}]
    save_conversation({"id": conversation_id, "status": "active", "messages": list(history)}, user_id)
    turn = await run_agent_turn(
        conversation_id=conversation_id,
        messages=history,
        user_text=question.text,
        user_id=user_id,
        user_profile={"display_name": USER, "timezone": TIMEZONE},
        model=None,
        agent_mode="know_me",
        agent_tone="auto",
        style_source_id=None,
        agent_name="Omi",
    )
    reply = " ".join(str(m.get("content") or "") for m in turn.messages[len(history) + 1:] if m.get("role") == "assistant")
    problem = check_answer(question, reply)
    return AnswerResult(question=question, reply=reply, passed=not problem, problem=problem)


def check_answer(question: Question, reply: str) -> str:
    text = reply.lower()
    missing = [group for group in question.answer if not any(re.search(pattern, text) for pattern in group)]
    if missing:
        return "missing " + " / ".join("|".join(group) for group in missing)
    if question.unknown and not any(re.search(pattern, text) for pattern in DONT_KNOW):
        return "did not say it does not know"
    hits = [pattern for pattern in question.forbidden if re.search(pattern, text)]
    return f"brought up {', '.join(hits)}" if hits else ""


__all__ = [
    "EXPORT",
    "QUESTIONS",
    "AnswerResult",
    "Question",
    "ReadingResult",
    "ask",
    "check_answer",
    "check_reading",
    "read_upload_case",
]
