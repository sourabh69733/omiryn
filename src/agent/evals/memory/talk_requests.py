"""How-to-talk requests: once the user asks to be talked to differently, does Omi keep doing it?

Each case plays a chat in which the user makes a request, then more ordinary chat, runs the real
background model, then asks the real reply model a question twice: later in the same chat, and in
a new chat (other chats must know it too). Checked in code, no AI judge:

- saved: an active how-to-talk (procedural) memory holds the request;
- replaced: when the user changes an earlier request, the old one is no longer active;
- followed: both replies keep the request (length, no question mark, no emoji).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable
from uuid import uuid4

from agent.cognition.background.service import run_background_cognition
from agent.runtime.orchestrator import run_agent_turn
from agent.shared.clock import utc_now
from storage import create_agent_memory, list_agent_memories, save_conversation, set_user_timezone

TIMEZONE = "Asia/Kolkata"
QUESTION = "space ke baare mein kuch interesting batao"
# Ordinary chat after the request, so "followed" tests it later in the chat, not just next turn.
LATER_CHAT = (
    ("user", "aaj office mein kaafi kaam tha"),
    ("assistant", "Lamba din tha phir."),
    ("user", "haan, ab ghar aa gaya"),
    ("assistant", "Achha, ab aaram karo."),
    ("user", "dinner mein paneer banaya"),
    ("assistant", "Paneer, badhiya choice."),
    ("user", "kal weekend hai finally"),
    ("assistant", "Weekend ka plan bana?"),
)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def _words(reply: str) -> int:
    return len(reply.split())


@dataclass(frozen=True)
class Follow:
    what: str
    check: Callable[[str], bool]


SHORT = Follow("at most 30 words", lambda reply: _words(reply) <= 30)
NO_QUESTIONS = Follow("no question mark", lambda reply: "?" not in reply)
NO_EMOJI = Follow("no emoji", lambda reply: not _EMOJI.search(reply))
LONGER = Follow("more than 30 words", lambda reply: _words(reply) > 30)


@dataclass(frozen=True)
class TalkRequestCase:
    id: str
    request: str
    follow: Follow
    # Words that show a saved memory holds this request (regex, case-insensitive).
    saved: str
    # An earlier request this one replaces: (statement, value), seeded as an active memory.
    replaces: tuple[str, str] | None = None
    what: str = ""


TALK_REQUEST_CASES: tuple[TalkRequestCase, ...] = (
    TalkRequestCase(
        id="short_hinglish",
        request="yaar itna lamba mat likha karo, chhota rakho",
        follow=SHORT,
        saved=r"short|brief|concise|chhot|lamba|long",
        what="Shorter replies, asked in Hinglish.",
    ),
    TalkRequestCase(
        id="no_questions_hinglish",
        request="har baar sawal mat pucha karo yaar, irritating lagta hai",
        follow=NO_QUESTIONS,
        saved=r"question|sawal",
        what="No questions, asked in Hinglish.",
    ),
    TalkRequestCase(
        id="no_emoji",
        request="please don't use emojis when you talk to me",
        follow=NO_EMOJI,
        saved=r"emoji",
        what="No emojis, asked in English.",
    ),
    TalkRequestCase(
        id="switch_back",
        request="ab short mat likho, thoda detail mein bataya karo",
        follow=LONGER,
        saved=r"detail|longer|elaborat|more",
        replaces=("The user wants short replies.", "short replies"),
        what="An earlier 'keep it short' is changed to 'more detail'.",
    ),
)


@dataclass(frozen=True)
class TalkRequestResult:
    case: TalkRequestCase
    passed: bool
    problems: tuple[str, ...]
    how_to_talk: tuple[str, ...]
    same_chat_reply: str
    new_chat_reply: str
    errors: tuple[str, ...]


async def run_talk_request_case(case: TalkRequestCase) -> TalkRequestResult:
    user_id = f"talk-{case.id}-{uuid4().hex[:8]}"
    set_user_timezone(user_id, TIMEZONE)
    conversation_id = f"{user_id}-chat"
    start = utc_now() - timedelta(minutes=30)
    messages: list[dict[str, Any]] = []

    def say(role: str, text: str) -> None:
        sent = (start + timedelta(minutes=len(messages))).isoformat()
        messages.append({"role": role, "content": text, "created_at": sent})

    old_id = None
    if case.replaces:
        statement, value = case.replaces
        old_id = create_agent_memory(
            {
                "user_id": user_id,
                "kind": "procedural",
                "purposes": ["personalization"],
                "key": "conversation.reply_length",
                "value": value,
                "statement": statement,
                "confidence": 0.9,
                "importance": 0.8,
                "evidence": [{"conversation_id": f"{user_id}-old", "message_index": 0, "exact_quote": "keep it short", "observed_at": (start - timedelta(days=3)).isoformat()}],
            }
        )["id"]
    say("user", "hey")
    say("assistant", "Hey! Kya chal raha hai?")
    say("user", case.request)
    say("assistant", "Theek hai, samajh gaya.")
    for role, text in LATER_CHAT:
        say(role, text)
    save_conversation({"id": conversation_id, "status": "active", "messages": list(messages)}, user_id)

    errors: list[str] = []
    result = await run_background_cognition(conversation_id, user_id, messages)
    if result.get("status") in {"live_error", "live_invalid"}:
        errors.extend(str(error) for error in result.get("errors") or [])

    memories = list_agent_memories(user_id)
    active = [memory for memory in memories if memory["status"] == "active" and memory["kind"] == "procedural"]
    texts = [f"{memory.get('statement') or ''} {memory.get('value') or ''}".lower() for memory in active]

    problems: list[str] = []
    if not any(re.search(case.saved, text) for text in texts):
        problems.append("the request was not saved as a how-to-talk memory")
    if old_id and any(memory["id"] == old_id for memory in active):
        problems.append("the old request is still active")

    same = await _reply(conversation_id, user_id, messages)
    new_chat = f"{user_id}-new"
    save_conversation({"id": new_chat, "status": "active", "messages": []}, user_id)
    fresh = await _reply(new_chat, user_id, [])
    if not case.follow.check(same):
        problems.append(f"same chat reply broke it ({case.follow.what})")
    if not case.follow.check(fresh):
        problems.append(f"new chat reply broke it ({case.follow.what})")
    if errors:
        problems.append("background error")
    return TalkRequestResult(
        case=case,
        passed=not problems,
        problems=tuple(problems),
        how_to_talk=tuple(texts),
        same_chat_reply=same,
        new_chat_reply=fresh,
        errors=tuple(errors),
    )


async def _reply(conversation_id: str, user_id: str, messages: list[dict[str, Any]]) -> str:
    turn = await run_agent_turn(
        conversation_id=conversation_id,
        messages=messages,
        user_text=QUESTION,
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


__all__ = ["TALK_REQUEST_CASES", "TalkRequestCase", "TalkRequestResult", "run_talk_request_case"]
