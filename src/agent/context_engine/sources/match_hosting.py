"""Introductions Omi made for this user, so a normal reply knows about them: who, the plan, and how to
record what the user says came of it. Facts only; the model decides when any of it matters."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from agent.matching.hosting import CLOSED_STATUSES, OPEN_STATUSES, pair_facts
from agent.matching.pair_chat import chat_announced
from agent.shared.clock import utc_now
from agent.shared.timeline import parse_time, relative_day, user_zone

MATCH_HOSTING_SOURCE_TYPE = "match_hosting"
# A pair the user has not heard about yet (the introduction is queued) is not mentioned; a closed
# one stays for a few days, so "how did it go" lands on the right answer.
_CLOSED_FOR = timedelta(days=7)
_STATUS_WORDS = {
    "introduced": "introduced; you do not know yet whether they met",
    "met": "they met",
    "still_talking": "they met and are still in touch",
    "no_show": "it did not happen",
    "declined": "the user said no to it",
}
# The other person ended it (a pass after the introduction, a block or a report): no reason is known here.
_CLOSED_BY_OTHER = "it is off, and not by this user's choice; you do not know why, so do not guess"
_CHAT_FACT = (
    "Where the status is introduced, met or still in touch, the two can write to each other directly in the "
    "app: Matches, then the person. You cannot see that chat. They talk there first: where no plan is set, do not "
    "propose a meet, a place or a time; meeting is theirs to decide."
)


def match_hosting_sources(user_id: str | None) -> list[dict[str, Any]]:
    if not user_id:
        return []
    from storage import get_user_timezone, match_pairs_for_user

    now = utc_now()
    zone = user_zone(get_user_timezone(user_id))
    lines = []
    asks = []
    open_chat = False
    for pair in match_pairs_for_user(user_id):
        plan = pair.get("plan") or {}
        told = (plan.get("told") or {}).get(user_id) or {}
        if pair["status"] == "asked" and told.get("sent"):
            facts = pair_facts(pair, user_id)
            mine = ((plan.get("answers") or {}).get(user_id) or {}).get("answer")
            state = "they said yes; the other person has not answered yet" if mine == "accept" else "they have not answered yet"
            asks.append(f"- {facts['name']} (pair id {pair['id']}): you offered to introduce them; {state}.")
            continue
        if pair["status"] not in OPEN_STATUSES | CLOSED_STATUSES or not told.get("sent"):
            continue
        introduced_at = parse_time(pair.get("introduced_at")) or parse_time(told.get("at"))
        if pair["status"] in CLOSED_STATUSES and introduced_at and now - introduced_at > _CLOSED_FOR:
            continue
        facts = pair_facts(pair, user_id)
        when = relative_day(introduced_at.astimezone(zone).date(), now.astimezone(zone).date()) if introduced_at else "recently"
        plan_words = ", ".join(part for part in (plan.get("place"), plan.get("when")) if part) or "no place or time set yet"
        status_words = _STATUS_WORDS.get(pair["status"], pair["status"])
        if pair["status"] == "declined" and plan.get("closed_by") not in (None, user_id):
            status_words = _CLOSED_BY_OTHER
        lines.append(f"- {facts['name']} (pair id {pair['id']}): introduced {when}. Plan: {plan_words}. Status: {status_words}.")
        open_chat = open_chat or pair["status"] in OPEN_STATUSES
    sources = []
    if asks:
        sources.append(
            {
                "source_type": MATCH_HOSTING_SOURCE_TYPE,
                "title": "Someone you offered to introduce",
                "content": "\n".join(
                    [
                        "You told this user about these people from their group and asked whether to introduce them:",
                        *asks,
                        "Share nothing more about them than the reasons you gave. When the user gives a clear answer (yes, "
                        "introduce them; or no), record it with answer_match and the pair id in the same turn, then answer as a "
                        "friend would. A question about the person is not an answer; a maybe is not an answer.",
                    ]
                ),
                "metadata": {"asks": len(asks)},
            }
        )
    if not lines:
        return sources
    return sources + [
        {
            "source_type": MATCH_HOSTING_SOURCE_TYPE,
            "title": "Introductions you made",
            "content": "\n".join(
                [
                    "You introduced this user to these people from their group, in this chat:",
                    *lines,
                    "They are real people who also talk with you. Share nothing about them beyond the reasons you "
                    "already gave: not their words, notes or contact details, and do not carry messages between them. "
                    "When the user tells you how it went (they met, it did not happen, they want to drop it, they are "
                    "still in touch), record it with record_match_outcome and the pair id, in the same turn, then "
                    "answer as a friend would. A change of place or time goes through the person who runs their "
                    "group; say so plainly rather than promising to arrange it.",
                    *([_CHAT_FACT] if open_chat and chat_announced() else []),
                ]
            ),
            "metadata": {"pairs": len(lines)},
        }
    ]


__all__ = ["MATCH_HOSTING_SOURCE_TYPE", "match_hosting_sources"]
