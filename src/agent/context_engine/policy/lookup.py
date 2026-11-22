"""The look-up plan: does this message need facts from the web, and which searches would find them.

A small fast model writes the plan before the reply is drafted, so looking things up does not rest
on how good the reply model is with tools. This module holds what that model reads and how its
answer is read; the step that runs the searches is `agent.runtime.steps.lookup`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

QUERY_CHARS = 200
RECENT_MESSAGES = 6
RECENT_CHARS = 300

LOOKUP_PLAN_SYSTEM_PROMPT = """You decide whether a companion app should search the web before it answers a user's
message, and you write the searches. The companion's own knowledge is old: anything that changes
over time, it may get wrong. Return one JSON object only:
{"lookup": true or false, "searches": [{"query": "...", "recent_days": number or null}]}

Input: today (the date where the user is), place (where the user lives; may be empty or only
estimated), recent (the last few messages, to tell what "it" or "uska" refers to), message (what
the user just wrote, often in Hinglish).

Most messages need no look-up. Look up only when the user is asking for a fact that has to be
checked, because it changes or must be exact:
- a date, deadline, form, result or schedule, or whether something is open right now
- a figure: pay, price, fee, cut-off, rate, what is normal this year
- a rule, eligibility or the steps set by a company, a university or a government
- news, or whether something said about a company, product, exam or public person is true
- current openings, events, releases, places

Do not look up when the user wants:
- your view or advice (which to choose, is it worth it, what should I do, how do I say this)
- comfort or a talk about a feeling or a setback. Search results make such a reply cold.
- a general explanation of a term or an idea that does not change from year to year
- something written or rewritten (a mail, a message), maths, a joke, small talk
- anything about their own life or past chats
The topic alone is never the reason: a message about jobs, exams or money is often advice or
feelings, and then the answer is no. If you are not sure, the answer is no.

Searches:
- One is usually enough; never more than the answer needs. Each is a short web query in English
  with the exact names (the exam, company, programme) and the year when it matters.
- Add the country or city from place when the answer depends on where the user lives (jobs, exams,
  pay, prices, rules, events).
- recent_days: a number (7 or 30) only when the user asks about news, something that just
  happened; otherwise null. A rule, a date or a figure is not news.
- Never put a private person's name or anything personal about the user in a query. Their city or
  country is fine.
- Nothing to look up: {"lookup": false, "searches": []}"""


@dataclass(frozen=True)
class PlannedSearch:
    query: str
    recent_days: int | None = None

    @property
    def arguments(self) -> dict[str, Any]:
        """As the web_search tool takes them."""
        return {"query": self.query, **({"recent_days": self.recent_days} if self.recent_days else {})}


def max_searches() -> int:
    """How many searches one turn's plan may run (AGENT_LOOKUP_MAX_SEARCHES, default 2). Each one
    costs a search credit and adds to what the reply model reads."""
    try:
        return max(1, min(4, int(os.getenv("AGENT_LOOKUP_MAX_SEARCHES", "2"))))
    except ValueError:
        return 2


def lookup_plan_input(user_text: str, history: list[dict[str, Any]], *, today: str, place: str | None) -> str:
    """What the planning model reads: the message, a little of the chat before it, and two facts
    code knows (the date and where the user is)."""
    recent = [
        f'{message.get("role")}: {str(message.get("content") or "")[:RECENT_CHARS]}'
        for message in history[-RECENT_MESSAGES:]
        if message.get("role") in {"user", "assistant"} and str(message.get("content") or "").strip()
    ]
    return json.dumps({"today": today, "place": place or "", "recent": recent, "message": user_text}, ensure_ascii=False)


def planned_searches(raw: Any, limit: int | None = None) -> list[PlannedSearch]:
    """The searches in the model's answer, cleaned. Anything malformed means no search."""
    if not isinstance(raw, dict) or raw.get("lookup") is not True:
        return []
    found: list[PlannedSearch] = []
    for item in raw.get("searches") or []:
        text = item.get("query") if isinstance(item, dict) else item
        query = " ".join(str(text or "").split())[:QUERY_CHARS]
        if not query or any(query.casefold() == other.query.casefold() for other in found):
            continue
        days = item.get("recent_days") if isinstance(item, dict) else None
        days = days if isinstance(days, int) and not isinstance(days, bool) and 0 < days <= 365 else None
        found.append(PlannedSearch(query, days))
    return found[: limit or max_searches()]


__all__ = ["LOOKUP_PLAN_SYSTEM_PROMPT", "PlannedSearch", "lookup_plan_input", "max_searches", "planned_searches"]
