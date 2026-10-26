"""Checks a draft reply against what the user asked about how to be talked to.

The reply model sees these requests in <how_to_talk> but often drifts from them. A separate,
stronger model reads only the requests and the draft and names the ones it breaks; the reply then
gets one rewrite. Only users with saved requests pay for the check.
"""

from __future__ import annotations

import json
from typing import Any

HOW_TO_TALK_SOURCE_TYPE = "how_to_talk"

REQUEST_CHECK_SYSTEM_PROMPT = """You check one chat reply against requests the user made about how the
companion should talk to them.

Input JSON: {"requests": ["..."], "reply": "..."}. Bubbles in the reply are separated by
<next_message>.

A request is broken when the reply goes against it, for example:
- "no questions": any question at all, including "did you know ...?" or "right?".
- short replies: in a chat, short is one or two brief sentences, about 25 words in all; more breaks it.
- more detail or longer replies: fewer than about 40 words, or only one or two sentences, breaks it.
- "no emojis": any emoji. "no advice": telling them what to do. A subject they asked not to bring up:
  any mention of it.
Requests the reply has no chance to break (it never comes up) are kept.

Return JSON only: {"broken": ["<request copied exactly as given>"]}, or {"broken": []}."""


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


def request_check_input(reply: str, requests: list[str]) -> str:
    return json.dumps({"requests": requests, "reply": reply}, ensure_ascii=False)


def broken_requests(raw: Any, requests: list[str]) -> list[str]:
    """Only requests that were given count; anything else the checker wrote is ignored."""
    given = set(requests)
    broken = raw.get("broken") if isinstance(raw, dict) else None
    return [item for item in dict.fromkeys(broken or []) if isinstance(item, str) and item in given]


def broken_requests_reason(broken: list[str]) -> str:
    return "it goes against how the user asked you to talk to them: " + "; ".join(broken)


__all__ = [
    "HOW_TO_TALK_SOURCE_TYPE",
    "REQUEST_CHECK_SYSTEM_PROMPT",
    "broken_requests",
    "broken_requests_reason",
    "how_to_talk_requests",
    "request_check_input",
]
