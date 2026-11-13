"""The chat two introduced people have with each other in the app, and how either one ends it.

Omi introduces and then steps back: the two write to each other directly, Omi never reads the chat
and never carries messages. Code decides who may read and write; a block or a report closes the
pair for both, keeps the two out of each other's future candidates, and the other person is told
only that it is off.
"""

from __future__ import annotations

import os
from typing import Any

from agent.shared.clock import utc_now

from .asking import record_answer
from .hosting import CLOSED_STATUSES, OPEN_STATUSES, _defer_to_daytime, _host, hosting_conversation, pair_facts

MATCH_CLOSED_JOB = "match_closed"
# A pair whose chat the two may still read; only an open one takes new messages.
READABLE_STATUSES = OPEN_STATUSES | CLOSED_STATUSES

_CLOSED_INSTRUCTIONS = """

AN INTRODUCTION IS OFF
The introduction to {name} is off: the two will not be meeting or writing to each other through
Omiryn any more. If the recent chat shows the user already knows, reply with exactly: SKIP
Otherwise say so in one short bubble, lightly: it is not going ahead, no reason given, no blame on
anyone, and you will keep an eye out for someone else. Do not say why and do not guess.
"""
_CLOSED_CUE = "(The user has said nothing new. Tell them now.)"


def chat_announced() -> bool:
    """Whether the app has the chat screen, so Omi may point people to it. Off until the screen ships."""
    return os.getenv("MATCH_CHAT_IN_APP", "").strip().lower() in {"1", "true", "yes", "on"}


def other_user(pair: dict[str, Any], user_id: str) -> str:
    return pair["user_b"] if pair["user_a"] == user_id else pair["user_a"]


def chat_state(pair: dict[str, Any], user_id: str, *, blocks: set[frozenset[str]] | None = None) -> dict[str, Any]:
    """What this person may do in the pair's chat: read it, write in it.

    `blocks` is every blocked pair touching the user, passed in when many pairs are checked at once.
    """
    member = user_id in (pair["user_a"], pair["user_b"])
    readable = member and pair["status"] in READABLE_STATUSES
    is_open = readable and pair["status"] in OPEN_STATUSES
    if is_open:
        if blocks is None:
            from storage import blocked_match_pairs

            blocks = blocked_match_pairs([user_id])
        is_open = frozenset((pair["user_a"], pair["user_b"])) not in blocks
    return {"readable": readable, "open": is_open}


def close_pair(pair_id: str, user_id: str, *, block: bool, reason: str | None = None, note: str | None = None) -> dict[str, Any]:
    """End a pair from one side: an optional report for the team, an optional block, the pair declined.

    Returns {"ok", "status", "error"?}; status is what this person's card now says ("blocked" or
    "declined"). The other person, if they had heard about the pair, is told only that it is off.
    """
    from agent.jobs.queue import schedule_job
    from storage import block_match_user, get_match_pair, save_match_report, update_match_pair_plan

    pair = get_match_pair(pair_id)
    if pair is None or user_id not in (pair["user_a"], pair["user_b"]):
        return {"ok": False, "error": "unknown_pair"}
    if pair["status"] not in READABLE_STATUSES | {"asked"}:
        return {"ok": False, "error": "not_open", "status": pair["status"]}
    other = other_user(pair, user_id)
    if reason:
        save_match_report(pair_id, user_id, other, reason, note)
    if block:
        block_match_user(user_id, other, pair_id=pair_id)
    if pair["status"] == "asked":
        # Not introduced yet: the same path as "Not for me", so the other person hears "not this week".
        record_answer(pair_id, user_id, "pass")
    elif pair["status"] in OPEN_STATUSES:
        now = utc_now().isoformat()

        def closed(plan: dict[str, Any]) -> dict[str, Any]:
            plan.setdefault("outcomes", []).append({"user_id": user_id, "outcome": "declined", "note": None, "at": now})
            plan["closed_by"] = user_id
            return plan

        update_match_pair_plan(pair_id, closed, status="declined")
        told = (((pair.get("plan") or {}).get("told") or {}).get(other) or {}).get("sent")
        if told:
            conversation = hosting_conversation(other)
            schedule_job(MATCH_CLOSED_JOB, other, conversation["id"] if conversation else None, payload={"pair_id": pair_id}, key=f"{pair_id}:closed")
    return {"ok": True, "status": "blocked" if block else "declined"}


async def run_match_closed_job(job: dict[str, Any]) -> bool:
    from storage import get_match_pair

    pair_id = str((job.get("payload") or {}).get("pair_id") or "")
    pair = get_match_pair(pair_id) if pair_id else None
    user_id = str(job["user_id"])
    if pair is None or user_id not in (pair["user_a"], pair["user_b"]) or pair["status"] != "declined":
        return False
    if _defer_to_daytime(job):
        return False
    facts = pair_facts(pair, user_id)
    return await _host(user_id, pair, kind="match_closed", user_text=f"meeting {facts['name']}", instructions=_CLOSED_INSTRUCTIONS.format(name=facts["name"]), cue=_CLOSED_CUE)


__all__ = ["MATCH_CLOSED_JOB", "READABLE_STATUSES", "chat_announced", "chat_state", "close_pair", "other_user", "run_match_closed_job"]
