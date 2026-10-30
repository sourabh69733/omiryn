"""Checks a draft reply against what the user asked about how to be talked to.

The reply model sees these requests in <how_to_talk> but often drifts from them. A separate,
stronger model reads only the requests and the draft and names the ones it breaks; the reply then
gets one rewrite. Requests are saved only after the chat goes quiet, so the check also reads the
user's messages from this session: "stop asking that" or "english?" holds from the next reply.
"""

from __future__ import annotations

import json
from typing import Any

from agent.shared.timeline import current_session_start

from .asked_questions import AskedQuestion

HOW_TO_TALK_SOURCE_TYPE = "how_to_talk"
# The request the checker names when a reply asks a closed question again.
DO_NOT_ASK_AGAIN = 'do not ask again: "{question}"'
# The user's latest messages in this session the checker reads, newest last.
RECENT_USER_MESSAGES = 8
_MAX_MESSAGE_CHARS = 300

REQUEST_CHECK_SYSTEM_PROMPT = """You check one chat reply against requests the user made about how the
companion should talk to them.

Input JSON: {"requests": ["..."], "recent_user_messages": ["..."], "asked_questions": [...],
"reply": "..."}. requests are saved ones. recent_user_messages are the user's latest messages in
this chat, newest last; a request they made there counts too, such as a language to use or
something to stop. Plain chat in those messages is not a request. asked_questions are questions
the companion already asked in this chat, each with how many times and what the user said right
after each time ("user_said", null when nothing came yet). A question the user turned down (called
it pointless, refused, asked to stop), did not answer twice, or already answered is closed: if the
reply asks it again in any words, report it as the request `do not ask again: "<question>"`, copied
exactly with the question as given. Bubbles in the reply are separated by <next_message>.

A request is broken when the reply goes against it, for example:
- "no questions": any question at all, including "did you know ...?" or "right?".
- short replies: in a chat, short is one or two brief sentences, about 25 words in all; more breaks it.
- more detail or longer replies: fewer than about 40 words, or only one or two sentences, breaks it.
- "no emojis": any emoji. "no advice": telling them what to do. A subject they asked not to bring up:
  any mention of it.
Requests the reply has no chance to break (it never comes up) are kept.

Return JSON only: {"broken": ["<the request, or the user message holding it, copied exactly as given>"]},
or {"broken": []}."""


def request_check_reason(
    reply: str,
    requests: list[str],
    recent_user_messages: list[str],
    asked: list[AskedQuestion],
) -> str | None:
    """Why this draft is worth one checker call, or None when no code fact says it could break a
    request. The check costs a model call on every reply it runs for, so it runs when:

    - the user has saved how-to-talk requests (the checker judges every one of them);
    - the draft asks a question and a question Omi asked this session already got an answer or a
      brush-off, so the draft may be asking a closed one again in other words;
    - a message in this session matches the explicit constraint or feedback phrases the turn
      understanding already recognises (no questions, no advice, just listen, "you keep asking").

    Not caught, by design: a request made this session in words none of those phrases cover, when
    the draft has no question. It holds once the background run saves it as a how-to-talk memory.
    AGENT_REQUEST_CHECK=always restores the check on every reply.
    """
    if requests:
        return "saved_requests"
    if "?" in reply and any(any(said for said in item.user_said) for item in asked):
        return "question_after_asked"
    from agent.context_engine.understanding.rules.stance import explicit_constraints, feedback_kind

    if any(explicit_constraints(text) or feedback_kind(text) for text in recent_user_messages):
        return "request_in_session"
    return None


def how_to_talk_requests(context_sources: list[dict[str, Any]]) -> list[str]:
    """The saved requests that reached this reply, one per line of the how-to-talk source."""
    requests: list[str] = []
    for source in context_sources:
        if source.get("source_type") != HOW_TO_TALK_SOURCE_TYPE:
            continue
        for line in str(source.get("content") or "").splitlines():
            if line.startswith("- ") and line[2:].strip():
                requests.append(line[2:].strip())
    return requests


def recent_user_requests(history: list[dict[str, Any]], user_text: str) -> list[str]:
    """The user's latest messages in this session, where a request may not be saved yet."""
    session = history[current_session_start(history):]
    texts = [str(message.get("content") or "") for message in session if message.get("role") == "user"]
    if user_text and (not texts or texts[-1] != user_text):
        texts.append(user_text)
    return [text.strip()[:_MAX_MESSAGE_CHARS] for text in texts[-RECENT_USER_MESSAGES:] if text.strip()]


def request_check_input(
    reply: str,
    requests: list[str],
    recent_user_messages: list[str] | None = None,
    asked: list[AskedQuestion] | None = None,
) -> str:
    return json.dumps(
        {
            "requests": requests,
            "recent_user_messages": recent_user_messages or [],
            "asked_questions": [
                {"question": item.question, "times": item.times, "user_said": item.user_said} for item in asked or []
            ],
            "reply": reply,
        },
        ensure_ascii=False,
    )


def asked_question_requests(asked: list[AskedQuestion]) -> list[str]:
    """The request strings the checker may name for the asked questions."""
    return [DO_NOT_ASK_AGAIN.format(question=item.question) for item in asked]


def broken_requests(raw: Any, requests: list[str]) -> list[str]:
    """Only requests that were given count; anything else the checker wrote is ignored."""
    given = set(requests)
    broken = raw.get("broken") if isinstance(raw, dict) else None
    return [item for item in dict.fromkeys(broken or []) if isinstance(item, str) and item in given]


def broken_requests_reason(broken: list[str]) -> str:
    return "it goes against what the user asked of you: " + "; ".join(f'"{item}"' for item in broken)


__all__ = [
    "DO_NOT_ASK_AGAIN",
    "HOW_TO_TALK_SOURCE_TYPE",
    "asked_question_requests",
    "REQUEST_CHECK_SYSTEM_PROMPT",
    "broken_requests",
    "broken_requests_reason",
    "how_to_talk_requests",
    "recent_user_requests",
    "request_check_input",
    "request_check_reason",
]
