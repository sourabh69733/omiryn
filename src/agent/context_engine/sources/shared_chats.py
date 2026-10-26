"""What the reply sees of the chats the user uploaded: little by default, more when it is asked about.

Every reply gets one index line per upload ("Farheen Parvez, 15-21 Oct: work stress, AI tasks"), so
Omi knows the chat exists and never claims it has none. When the message names the other person, the
chat's summary, facts about that person, plans and main topics come in. When it shares words with
a topic, that topic comes in with a few real lines from both sides, so Omi can quote instead of
guessing. Code only matches; what the chat holds was written when it was uploaded.
"""

from __future__ import annotations

import math
import re
from typing import Any

from storage import get_conversation
from storage.upload_digests import list_upload_digests

SHARED_CHATS_SOURCE_TYPE = "shared_chats"
# Topics whose words overlap the message at least this much come in (cosine of word sets).
TOPIC_MATCH = 0.12
MAX_TOPICS = 3
QUOTES_PER_TOPIC = 4
QUOTE_CHARS = 160
_WORD = re.compile(r"[\w']+")


def uploaded_chat_sources(user_id: str | None, user_text: str, conversation_id: str | None = None) -> list[dict[str, Any]]:
    if not user_id:
        return []
    digests = list_upload_digests(user_id)
    if not digests:
        return []
    subject = subject_person(user_id, user_text, conversation_id, digests)
    lines = [
        "Chats the user uploaded (WhatsApp with someone else), so you know these people through them. "
        "Asked about someone listed here, share what this says about them and the chat. The other "
        "person's words are theirs, not the user's. If asked about something not here, search the chat "
        "(search_chats) before saying you don't have it; never guess.",
    ]
    for stored in digests:
        digest = stored["digest"]
        lines.append(f"- {_index(stored, digest)}")
        named = stored["partner_name"] == subject
        topics = matching_topics(digest.get("threads") or [], user_text, ignore=stored["partner_name"])
        if named:
            lines.extend(_about_chat(digest))
            topics = topics or (digest.get("threads") or [])[:MAX_TOPICS]
        if topics:
            quotes = _quotes(stored, user_id, topics[:2], digest.get("chat_with"))
            lines.append("  Topics that fit this message:")
            for topic in topics:
                lines.append(f"  * {_topic(topic)}")
            if quotes:
                lines.append("  Lines from the chat:")
                lines.extend(f"    {quote}" for quote in quotes)
    return [
        {
            "source_type": SHARED_CHATS_SOURCE_TYPE,
            "title": "Chats the user uploaded",
            "content": "\n".join(lines),
            "metadata": {"uploads": len(digests)},
        }
    ]


def names_uploaded_person(user_id: str | None, user_text: str, conversation_id: str | None = None) -> bool:
    """The message is about someone from a chat the user uploaded (by name, or "she" after them)."""
    return bool(user_id) and subject_person(user_id, user_text, conversation_id) is not None


# The last user messages a "she" or "her" can point back to.
SUBJECT_LOOKBACK = 4


def subject_person(
    user_id: str,
    user_text: str,
    conversation_id: str | None = None,
    digests: list[dict[str, Any]] | None = None,
) -> str | None:
    """Who from the uploaded chats this message is about: one it names, else the one the user's
    last few messages named (so "what is her relationship status?" after "farheen?" is about her)."""
    partners = [stored["partner_name"] for stored in (digests if digests is not None else list_upload_digests(user_id)) if stored["partner_name"]]
    if not partners:
        return None
    named = [partner for partner in partners if _names(partner, user_text)]
    if named:
        return named[0]
    if not conversation_id:
        return None
    recent = [
        str(message.get("content") or "")
        for message in (get_conversation(conversation_id, user_id) or {}).get("messages") or []
        if message.get("role") == "user"
    ][-SUBJECT_LOOKBACK:]
    for text in reversed(recent):
        found = [partner for partner in partners if _names(partner, text)]
        if found:
            return found[0]
    return None


def matching_topics(threads: list[dict[str, Any]], user_text: str, *, ignore: str | None = None) -> list[dict[str, Any]]:
    """Topics that share enough words with the message, best first. The other person's name is in
    most topics, so it never counts as a match by itself (naming them brings the chat anyway)."""
    name = _words(ignore or "")
    words = _words(user_text) - name
    scored = []
    for thread in threads:
        text = " ".join(str(thread.get(key) or "") for key in ("title", "summary", "user_view", "other_view"))
        score = _overlap(words, _words(text) - name)
        if score >= TOPIC_MATCH:
            scored.append((score, thread))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [thread for _, thread in scored[:MAX_TOPICS]]


def _names(partner: str | None, user_text: str) -> bool:
    """The message names the other person: any part of their name, as a whole word."""
    if not partner:
        return False
    words = set(_WORD.findall(user_text.casefold()))
    return any(len(part) > 2 and part in words for part in _WORD.findall(partner.casefold()))


def _index(stored: dict[str, Any], digest: dict[str, Any]) -> str:
    dates = digest.get("chat_dates") or {}
    when = f" ({dates.get('from')} to {dates.get('to')})" if dates.get("from") else ""
    who = stored.get("partner_name") or "Notes"
    return f"{who}{when}: {digest.get('index_line') or ''}".strip()


def _about_chat(digest: dict[str, Any]) -> list[str]:
    lines = []
    if digest.get("summary"):
        lines.append(f"  Summary: {digest['summary']}")
    card = digest.get("person_card") or {}
    if card:
        lines.extend(person_card_lines(card, digest.get("chat_with") or "them"))
    else:
        person = [item["text"] for item in digest.get("person") or [] if item.get("text")]
        if person:
            lines.append(f"  About {digest.get('chat_with') or 'them'}: " + " ".join(person[:8]))
    plans = [
        item["what"] + (" (" + str(item["when"])[:10] + ")" if item.get("when") else "")
        for item in digest.get("plans") or []
        if item.get("what")
    ]
    if plans:
        lines.append("  Plans mentioned: " + "; ".join(plans[:5]))
    return lines


def person_card_lines(card: dict[str, list[dict[str, Any]]], name: str) -> list[str]:
    """What is known about them, by kind, newest first, each with the real line it came from."""
    lines = [
        f"  What the chat says about {name} (newest first; each with the exact line and its date). This "
        "is all that is known about them: anything not here, say you don't know.",
    ]
    for category, facts in card.items():
        for position, fact in enumerate(facts[:3]):
            label = category.capitalize() if position == 0 else " " * len(category)
            lines.append(f'  - {label}: {fact["fact"]} [{fact.get("date") or "date unknown"}, {fact["speaker"]}: "{fact["quote"]}"]')
    return lines


def _topic(thread: dict[str, Any]) -> str:
    when = f" [{thread.get('started')}]" if thread.get("started") else ""
    views = "; ".join(
        f"{label}: {thread[key]}" for key, label in (("user_view", "user"), ("other_view", "them")) if thread.get(key)
    )
    return f"{thread.get('title')}{when}: {thread.get('summary') or ''}{f' ({views})' if views else ''}"


def _quotes(stored: dict[str, Any], user_id: str, topics: list[dict[str, Any]], partner: str | None) -> list[str]:
    """A few real lines per topic from the hidden chat, both sides, oldest first."""
    conversation = get_conversation(stored["conversation_id"], user_id)
    messages = list((conversation or {}).get("messages") or [])
    quotes = []
    for topic in topics:
        picked = _spread([index for index in topic.get("lines") or [] if 0 <= index < len(messages)], QUOTES_PER_TOPIC)
        for index in picked:
            message = messages[index]
            who = "User" if message.get("role") == "user" else (message.get("speaker") or partner or "Them")
            text = " ".join(str(message.get("content") or "").split())
            quotes.append(f'{who}: "{text[:QUOTE_CHARS]}{"…" if len(text) > QUOTE_CHARS else ""}"')
    return quotes


def _spread(indexes: list[int], count: int) -> list[int]:
    """Evenly spaced picks, so a long topic shows its start, middle and end."""
    if len(indexes) <= count:
        return indexes
    step = (len(indexes) - 1) / (count - 1)
    return [indexes[round(position * step)] for position in range(count)]


def _words(text: str) -> set[str]:
    # Words of 3 letters or less ("are", "how", "kya") match everything.
    return {word for word in _WORD.findall(text.casefold()) if len(word) > 3}


def _overlap(left: set[str], right: set[str]) -> float:
    return len(left & right) / math.sqrt(len(left) * len(right)) if left and right else 0.0


__all__ = ["SHARED_CHATS_SOURCE_TYPE", "matching_topics", "names_uploaded_person", "subject_person", "uploaded_chat_sources"]
