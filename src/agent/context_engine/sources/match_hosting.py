"""Introductions Omi made for this user, so a normal reply knows about them: who, the plan, and how to
record what the user says came of it. Facts only; the model decides when any of it matters."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from agent.matching.hosting import CLOSED_STATUSES, OPEN_STATUSES, pair_facts
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


def match_hosting_sources(user_id: str | None) -> list[dict[str, Any]]:
    if not user_id:
        return []
    from storage import get_user_timezone, match_pairs_for_user

    now = utc_now()
    zone = user_zone(get_user_timezone(user_id))
    lines = []
    for pair in match_pairs_for_user(user_id):
        plan = pair.get("plan") or {}
        told = (plan.get("told") or {}).get(user_id) or {}
        if pair["status"] not in OPEN_STATUSES | CLOSED_STATUSES or not told.get("sent"):
            continue
        introduced_at = parse_time(pair.get("introduced_at")) or parse_time(told.get("at"))
        if pair["status"] in CLOSED_STATUSES and introduced_at and now - introduced_at > _CLOSED_FOR:
            continue
        facts = pair_facts(pair, user_id)
        when = relative_day(introduced_at.astimezone(zone).date(), now.astimezone(zone).date()) if introduced_at else "recently"
        plan_words = ", ".join(part for part in (plan.get("place"), plan.get("when")) if part) or "no place or time set yet"
        lines.append(f"- {facts['name']} (pair id {pair['id']}): introduced {when}. Plan: {plan_words}. Status: {_STATUS_WORDS.get(pair['status'], pair['status'])}.")
    if not lines:
        return []
    return [
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
                ]
            ),
            "metadata": {"pairs": len(lines)},
        }
    ]


__all__ = ["MATCH_HOSTING_SOURCE_TYPE", "match_hosting_sources"]
