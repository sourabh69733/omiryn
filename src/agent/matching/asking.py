"""Ask both: before any introduction, each person hears that there is someone and why, and says
"say hi" or "not for me". Both yes inside the window leads to the introduction (agent.matching.hosting);
one pass closes the pair and the other person hears only "not this week"; silence is a pass for
this week and the pair may come back once.

Code decides what goes out and when; the reply model writes every message from the facts it is
given (first name, reasons, difference). The answer comes through a tool in a normal turn, or
through the two buttons in the app; both land in record_answer.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from agent.shared.clock import utc_now
from storage import get_match_pair, set_match_pair_plan, update_match_pair_plan

from .hosting import CLOSED_STATUSES, _defer_to_daytime, _host, hosting_conversation, pair_facts, schedule_hosting_jobs

logger = logging.getLogger(__name__)

MATCH_ASK_JOB = "match_ask"
MATCH_ASK_EXPIRE_JOB = "match_ask_expire"
MATCH_NOT_THIS_WEEK_JOB = "match_not_this_week"
ANSWERS = ("accept", "pass")
# How long both have to answer before the ask lapses.
ANSWER_WINDOW = timedelta(hours=48)

_ASK_INSTRUCTIONS = """

SOMEONE THEY MIGHT GET ALONG WITH
There is someone from {group} who also talks with you, {name}, and you think the two of them would
get along. You have not told {name} anything about the user yet. Tell the user, as a friend who
knows both would: who {name} is to them in one line (nothing beyond the reasons below) and why you
think they would click, in plain words, using only these reasons:
{reasons}
{difference}Then ask whether they want you to introduce them, so the two can meet for a chai nearby. They can
say no and that is fine; make that clear without pushing. Share nothing else about {name}: not their
words to you, not their notes, no contact details. Two or three short bubbles separated by
<next_message>. Do not mention scores, matching, pools, operators or being automated.
"""
_ASK_CUE = "(The user has said nothing new. Tell them now.)"

_NOT_THIS_WEEK_INSTRUCTIONS = """

NOT THIS WEEK
The introduction to {name} you mentioned is not going to happen this week. If the recent chat shows
the user already knows, reply with exactly: SKIP
Otherwise say so in one short bubble, lightly: it did not work out this week, no reason given, no
blame on anyone, and you will keep an eye out. Do not say why, do not mention {name}'s answer or
silence, and do not promise a date.
"""
_NOT_THIS_WEEK_CUE = "(The user has said nothing new. Tell them now.)"


async def ask_pair(pair_id: str, *, created_by: str | None = None) -> dict[str, Any]:
    """Mark a proposed pair asked and queue the ask for both people, plus the lapse."""
    from agent.jobs.queue import schedule_job

    pair = get_match_pair(pair_id)
    if pair is None:
        raise LookupError("pair not found")
    if pair["status"] != "proposed":
        raise ValueError(f"pair is {pair['status']}, not proposed")
    now = utc_now()
    previous = pair.get("plan") or {}
    plan = {
        "asked_at": now.isoformat(),
        "answer_by": (now + ANSWER_WINDOW).isoformat(),
        "answers": {},
        "told": {},
        "outcomes": [],
        "expired_count": int(previous.get("expired_count") or 0),
        "set_by": created_by,
    }
    pair = set_match_pair_plan(pair_id, plan, status="asked")
    assert pair is not None
    for user_id in (pair["user_a"], pair["user_b"]):
        conversation = hosting_conversation(user_id)
        schedule_job(MATCH_ASK_JOB, user_id, conversation["id"] if conversation else None, payload={"pair_id": pair_id}, key=f"{pair_id}:ask")
    schedule_job(MATCH_ASK_EXPIRE_JOB, pair["user_a"], None, delay_seconds=ANSWER_WINDOW.total_seconds(), payload={"pair_id": pair_id}, key=f"{pair_id}:expire")
    return pair


async def run_match_ask_job(job: dict[str, Any]) -> bool:
    pair = _asked_pair(job)
    if pair is None:
        return False
    if _defer_to_daytime(job):
        return False
    user_id = str(job["user_id"])
    facts = pair_facts(pair, user_id)
    check = pair.get("check") or {}
    reasons = "\n".join(f"- {reason['text']}" for reason in check.get("reasons") or []) or "- (no written reasons: say the person who runs their group thought they would get along)"
    difference = f"One difference they could live with: {check['difference']['text']}\n" if check.get("difference") else ""
    instructions = _ASK_INSTRUCTIONS.format(name=facts["name"], group=facts["group"], reasons=reasons, difference=difference)
    sent = await _host(user_id, pair, kind="match_ask", user_text=f"meeting {facts['name']}", instructions=instructions, cue=_ASK_CUE)
    now = utc_now().isoformat()

    def told(current: dict[str, Any]) -> dict[str, Any]:
        current.setdefault("told", {})[user_id] = {"at": now, "sent": sent}
        return current

    update_match_pair_plan(pair["id"], told)
    return sent


def record_answer(pair_id: str, user_id: str, answer: str, note: str | None = None) -> dict[str, Any]:
    """One person's answer. Returns {"ok", "status", "error"?}. Both accept: the introduction is
    queued. A pass: the pair is declined and the other person, if told, hears "not this week"."""
    from agent.jobs.queue import schedule_job

    if answer not in ANSWERS:
        return {"ok": False, "error": "bad_answer"}
    pair = get_match_pair(pair_id)
    if pair is None or user_id not in (pair["user_a"], pair["user_b"]):
        return {"ok": False, "error": "unknown_pair"}
    if pair["status"] != "asked":
        return {"ok": False, "error": "not_open", "status": pair["status"]}
    other = pair["user_b"] if pair["user_a"] == user_id else pair["user_a"]
    now = utc_now()
    state = {"both": False, "other_answer": None}

    def record(plan: dict[str, Any]) -> dict[str, Any]:
        answers = plan.setdefault("answers", {})
        answers[user_id] = {"answer": answer, "note": (" ".join(str(note or "").split())[:200] or None), "at": now.isoformat()}
        state["other_answer"] = (answers.get(other) or {}).get("answer")
        state["both"] = answer == "accept" and state["other_answer"] == "accept"
        return plan

    if answer == "pass":
        pair = update_match_pair_plan(pair_id, record, status="declined")
        told = ((pair or {}).get("plan") or {}).get("told", {}).get(other) or {}
        if told.get("sent"):
            conversation = hosting_conversation(other)
            schedule_job(MATCH_NOT_THIS_WEEK_JOB, other, conversation["id"] if conversation else None, payload={"pair_id": pair_id}, key=f"{pair_id}:ntw")
        return {"ok": True, "status": "declined", "both": False}
    pair = update_match_pair_plan(pair_id, record)
    if state["both"]:
        pair = set_match_pair_plan(pair_id, dict((pair or {}).get("plan") or {}), status="introduced", introduced_at=now)
        assert pair is not None
        schedule_hosting_jobs(pair, now, None)
        return {"ok": True, "status": "introduced", "both": True}
    return {"ok": True, "status": "asked", "both": False}


async def run_match_ask_expire_job(job: dict[str, Any]) -> bool:
    """The window closed with the pair still asked: it lapses, and whoever said yes hears "not this week"."""
    from agent.jobs.queue import schedule_job

    pair = _asked_pair(job)
    if pair is None:
        return False

    def lapse(plan: dict[str, Any]) -> dict[str, Any]:
        plan["expired_count"] = int(plan.get("expired_count") or 0) + 1
        return plan

    pair = update_match_pair_plan(pair["id"], lapse, status="expired")
    assert pair is not None
    plan = pair.get("plan") or {}
    for user_id in (pair["user_a"], pair["user_b"]):
        answered = ((plan.get("answers") or {}).get(user_id) or {}).get("answer")
        told = ((plan.get("told") or {}).get(user_id) or {}).get("sent")
        if answered == "accept" and told:
            conversation = hosting_conversation(user_id)
            schedule_job(MATCH_NOT_THIS_WEEK_JOB, user_id, conversation["id"] if conversation else None, payload={"pair_id": pair["id"]}, key=f"{pair['id']}:ntw")
    return True


async def run_match_not_this_week_job(job: dict[str, Any]) -> bool:
    pair_id = str((job.get("payload") or {}).get("pair_id") or "")
    pair = get_match_pair(pair_id) if pair_id else None
    user_id = str(job["user_id"])
    if pair is None or user_id not in (pair["user_a"], pair["user_b"]) or pair["status"] not in CLOSED_STATUSES | {"expired"}:
        return False
    if _defer_to_daytime(job):
        return False
    facts = pair_facts(pair, user_id)
    return await _host(user_id, pair, kind="match_not_this_week", user_text=f"meeting {facts['name']}", instructions=_NOT_THIS_WEEK_INSTRUCTIONS.format(name=facts["name"]), cue=_NOT_THIS_WEEK_CUE)


def open_ask_for(user_id: str, pair: dict[str, Any]) -> bool:
    """The user has heard this ask and has not answered it."""
    plan = pair.get("plan") or {}
    told = ((plan.get("told") or {}).get(user_id) or {}).get("sent")
    answered = (plan.get("answers") or {}).get(user_id)
    return pair["status"] == "asked" and bool(told) and not answered


def _asked_pair(job: dict[str, Any]) -> dict[str, Any] | None:
    pair_id = str((job.get("payload") or {}).get("pair_id") or "")
    pair = get_match_pair(pair_id) if pair_id else None
    if pair is None or pair["status"] != "asked" or str(job["user_id"]) not in (pair["user_a"], pair["user_b"]):
        return None
    return pair


__all__ = [
    "ANSWERS",
    "ANSWER_WINDOW",
    "MATCH_ASK_EXPIRE_JOB",
    "MATCH_ASK_JOB",
    "MATCH_NOT_THIS_WEEK_JOB",
    "ask_pair",
    "open_ask_for",
    "record_answer",
    "run_match_ask_expire_job",
    "run_match_ask_job",
    "run_match_not_this_week_job",
]
