"""The fact check: does a drafted reply say what the companion just looked up, or something else?

A reply model handed the right page can still answer from memory (seen: the page said a PF
withdrawal needs 12 months without a job, the reply said 2). A small model compares the reply with
what was looked up this turn and names the facts that do not match. Code keeps a finding only when
its quotes are really in the reply and in the results, then asks the reply model for one rewrite.

This module holds what the checking model reads and how its answer is read; the step is
`check_facts` in `agent.runtime.steps.checks`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

# Tools whose results are facts from outside: a search, a page that was read.
LOOKUP_TOOLS = frozenset({"web_search", "read_page"})
EVIDENCE_CHARS = 12000
DRAFT_CHARS = 1500
MAX_PROBLEMS = 3
# A quote of what the results say counts when this share of its words is in the results.
FOUND_WORD_SHARE = 0.8

FACT_CHECK_SYSTEM_PROMPT = """You check one chat reply against what the companion looked up on the web for it.

Input JSON: {"today": the date and time where the user is, "question": what the user asked, "results":
[what the look-ups returned: extracts from web pages, or a page's text], "reply": the drafted reply}.
Bubbles in the reply are separated by <next_message>.

Report two kinds of problem.
- "conflicts": the reply states a specific fact (a date, a number, an amount, a name, a rule, a
  step, whether something is open or closed) and the results say something different about the
  same thing. A date in the results that is before today, given by the reply as open or coming up,
  is a conflict.
- "unsupported": the reply gives, as the answer and as known, a specific fact that changes over
  time and the results say nothing about it: a date, a price, an amount, a count, a deadline, or
  the name of a particular opening, programme, event, product or service.

Not a problem:
- The reply and the results say the same thing in other words or another language ("kal, 24
  November ko" and "on 24th November 2026" agree).
- A rounding of what the results say.
- A judgment or advice ("kaafi sahi hai", "bada risk hai", "focus on a portfolio"), even when it
  uses a number the user gave.
- General knowledge that does not change, what the user told the companion, and the current
  date or time (the companion knows them without looking anything up).
- A fact the reply clearly gives as a guess, as what usually happens, or as not confirmed.
- A reply that follows one result when the results disagree with each other.
If you are not sure, do not report it.

Quote exactly. "reply_says" is words copied from the reply. For a conflict, "found" is words copied
from the results.
Return one JSON object only:
{"conflicts": [{"reply_says": "...", "found": "..."}], "unsupported": [{"reply_says": "..."}]}
Nothing wrong: {"conflicts": [], "unsupported": []}"""


@dataclass(frozen=True)
class FactProblem:
    kind: str  # "conflict" or "unsupported"
    reply_says: str
    found: str = ""


def looked_up_evidence(messages: list[dict[str, Any]]) -> list[str]:
    """What the look-up tools returned in these messages, in order, within a total size."""
    evidence: list[str] = []
    room = EVIDENCE_CHARS
    for message in messages:
        if message.get("role") != "tool" or message.get("name") not in LOOKUP_TOOLS:
            continue
        text = _extracts(str(message.get("content") or ""))
        if text and room > 0:
            evidence.append(text[:room])
            room -= len(text[:room])
    return evidence


def _extracts(note: str) -> str:
    """A tool's note without its opening lines to the reply model (how to use the results, today's
    date): the checker must quote the pages, never our own instructions."""
    for mark in ("\n---\n", "\n["):
        if mark in note:
            return note.split(mark, 1)[1].strip() if mark == "\n---\n" else "[" + note.split(mark, 1)[1].strip()
    return note.strip()


def fact_check_input(reply: str, user_text: str, evidence: list[str], *, today: str) -> str:
    return json.dumps({"today": today, "question": user_text, "results": evidence, "reply": reply}, ensure_ascii=False)


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s%₹$.:/-]", " ", str(text or "").casefold()).split())


def _in_results(quote: str, results: str) -> bool:
    """The quote is in the results as written, or nearly: the model trims and joins when it copies."""
    quote = _plain(quote)
    if not quote:
        return False
    if quote in results:
        return True
    words = quote.split()
    # Every number in the quote has to be there: a figure is the fact.
    if any(word not in results for word in words if any(char.isdigit() for char in word)):
        return False
    return sum(1 for word in words if word in results) / len(words) >= FOUND_WORD_SHARE


def _same_figures(reply_says: str, found: str) -> bool:
    """Both quotes carry figures and the reply's are all in the results' quote: the two agree on the
    numbers, so this is the same fact in other words, not a conflict."""
    said, there = set(re.findall(r"\d+", reply_says)), set(re.findall(r"\d+", found))
    return bool(said) and said <= there


def fact_problems(raw: Any, reply: str, evidence: list[str]) -> list[FactProblem]:
    """The checker's findings that hold up: the reply really says it, and for a conflict the
    results really say the other thing. Anything else the checker wrote is dropped."""
    if not isinstance(raw, dict):
        return []
    said, results = _plain(reply), _plain(" ".join(evidence))
    problems: list[FactProblem] = []
    for kind, key in (("conflict", "conflicts"), ("unsupported", "unsupported")):
        for item in raw.get(key) or []:
            if not isinstance(item, dict):
                continue
            reply_says = " ".join(str(item.get("reply_says") or "").split())
            found = " ".join(str(item.get("found") or "").split())
            if not reply_says or _plain(reply_says) not in said:
                continue
            if kind == "conflict" and (not _in_results(found, results) or _same_figures(reply_says, found)):
                continue
            if kind == "unsupported" and _in_results(reply_says, results):
                continue  # the results do say it
            if any(problem.reply_says == reply_says for problem in problems):
                continue
            problems.append(FactProblem(kind, reply_says[:300], found[:300] if kind == "conflict" else ""))
    return problems[:MAX_PROBLEMS]


def fact_rewrite_instruction(draft: str, problems: list[FactProblem]) -> str:
    """The last message the model reads for the one rewrite: what to fix, and to leave the rest."""
    fixes = []
    for problem in problems:
        if problem.kind == "conflict":
            fixes.append(f'you wrote "{problem.reply_says}", but what you looked up says "{problem.found}"')
        else:
            fixes.append(
                f'you wrote "{problem.reply_says}" as a fact, and nothing you looked up says that: '
                "leave it out, or say plainly that you could not confirm it"
            )
    return (
        f'Rewrite needed: your draft reply was "{draft.strip()[:DRAFT_CHARS]}". It does not match what you '
        f"looked up: {'; '.join(fixes)}. Write the reply again with these fixed. For facts use only what "
        "you looked up. Keep everything else as it was: the same language, length and format rules."
    )


__all__ = [
    "FACT_CHECK_SYSTEM_PROMPT",
    "FactProblem",
    "LOOKUP_TOOLS",
    "fact_check_input",
    "fact_problems",
    "fact_rewrite_instruction",
    "looked_up_evidence",
]
