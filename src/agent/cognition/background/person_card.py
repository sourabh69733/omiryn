"""A card about the other person in an uploaded chat: facts by kind, each with its real line and date.

Answers about someone used to come from loose summaries and the newest few hundred lines, so older
facts (an engagement decided weeks ago) were missing and gaps got filled with guesses. The card is
read from the whole chat in parts, a few at a time. The model only names the kind, the fact and the
message index; code copies that message as the quote with its date and speaker, so a quote can never
be made up. Facts that say the same thing are joined, newest first, a few per kind.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any
from zoneinfo import ZoneInfo

from agent.providers import analyze_person_part
from agent.shared.timeline import parse_time

from .upload_prompt import PERSON_CARD_CATEGORIES

logger = logging.getLogger(__name__)

PART_MESSAGES = 60
AT_ONCE = 6
PER_CATEGORY = 6
QUOTE_CHARS = 220
# A cited line shorter than this ("Yep", "Yeah sure") shows the line before it too.
SHORT_QUOTE = 40
FACT_CHARS = 200
_WORD = re.compile(r"[\w']+")


async def build_person_card(
    messages: list[dict[str, Any]],
    partner: str,
    zone: ZoneInfo,
    *,
    conversation_id: str,
    model: str | None,
) -> dict[str, list[dict[str, Any]]]:
    """{category: [facts newest first]}; parts that fail are skipped, the card is best effort."""
    parts = [range(start, min(start + PART_MESSAGES, len(messages))) for start in range(0, len(messages), PART_MESSAGES)]
    gate = asyncio.Semaphore(AT_ONCE)

    async def read(part: range) -> list[dict[str, Any]]:
        async with gate:
            payload = {"chat_with": partner, "messages": [_message(messages[i], i, partner, zone) for i in part]}
            try:
                raw = await analyze_person_part(json.dumps(payload, ensure_ascii=False), conversation_id=conversation_id, model=model)
            except Exception as error:
                logger.warning("agent.person_card.part_failed error_type=%s", type(error).__name__)
                return []
            return checked_facts(raw, messages, part, partner, zone)

    found = [fact for facts in await asyncio.gather(*(read(part) for part in parts)) for fact in facts]
    return merge_facts(found, partner)


def checked_facts(raw: Any, messages: list[dict[str, Any]], part: range, partner: str, zone: ZoneInfo) -> list[dict[str, Any]]:
    """Facts that name a known kind and a message of this part; the quote comes from that message."""
    facts = []
    for item in (raw.get("facts") if isinstance(raw, dict) else None) or []:
        if not isinstance(item, dict):
            continue
        category, fact, line = item.get("category"), " ".join(str(item.get("fact") or "").split()), item.get("line")
        if category not in PERSON_CARD_CATEGORIES or not fact or not isinstance(line, int) or isinstance(line, bool) or line not in part:
            continue
        message = messages[line]
        quote = " ".join(str(message.get("content") or "").split())
        if not quote:
            continue
        quote = quote[:QUOTE_CHARS] + ("…" if len(quote) > QUOTE_CHARS else "")
        # A short line ("Yep") means nothing alone: show the line it answered.
        before = messages[line - 1] if line > 0 else None
        if before is not None and len(quote) < SHORT_QUOTE and str(before.get("content") or "").strip():
            asked = " ".join(str(before.get("content") or "").split())[:QUOTE_CHARS]
            quote = f'{_speaker(before, partner)}: "{asked}" → "{quote}"'
        sent = parse_time(message.get("created_at"))
        facts.append(
            {
                "category": category,
                "fact": fact[:FACT_CHARS],
                "line": line,
                "date": sent.astimezone(zone).date().isoformat() if sent else None,
                "speaker": _speaker(message, partner),
                "quote": quote,
            }
        )
    return facts


def merge_facts(facts: list[dict[str, Any]], partner: str = "") -> dict[str, list[dict[str, Any]]]:
    """Per kind, newest first; a fact that says the same as a newer one is dropped. Their name is
    in most facts, so it does not count towards two facts being the same."""
    name = _words(partner)
    card: dict[str, list[dict[str, Any]]] = {}
    for fact in sorted(facts, key=lambda item: (item.get("date") or "", item["line"]), reverse=True):
        kept = card.setdefault(fact["category"], [])
        if len(kept) >= PER_CATEGORY or any(_same(fact["fact"], other["fact"], name) for other in kept):
            continue
        kept.append({key: value for key, value in fact.items() if key != "category"})
    return {category: card[category] for category in PERSON_CARD_CATEGORIES if card.get(category)}


def _same(left: str, right: str, ignore: set[str] = frozenset()) -> bool:
    a, b = _words(left) - ignore, _words(right) - ignore
    return bool(a and b) and len(a & b) / len(a | b) >= 0.6


def _words(text: str) -> set[str]:
    return {word for word in _WORD.findall(text.casefold()) if len(word) > 3}


def _speaker(message: dict[str, Any], partner: str) -> str:
    return "User" if message.get("role") == "user" else (message.get("speaker") or partner)


def _message(message: dict[str, Any], index: int, partner: str, zone: ZoneInfo) -> dict[str, Any]:
    sent = parse_time(message.get("created_at"))
    return {
        "i": index,
        "from": "user" if message.get("role") == "user" else (message.get("speaker") or partner),
        "at": sent.astimezone(zone).date().isoformat() if sent else None,
        "text": message.get("content"),
    }


__all__ = ["build_person_card", "checked_facts", "merge_facts"]
