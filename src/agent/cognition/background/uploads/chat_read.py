"""The read: what an uploaded chat says about the two people in it.

Two halves. Code counts what can be counted from the stored chat: how long, how often, who writes
first, who answers faster, who writes more, who laughs, who is up at night. One model call writes
what cannot be counted (the running jokes, what they keep coming back to, where they rub, a short
roast), naming the lines it means; code keeps an item only when those lines exist.

A model shown a thin sample of a long chat cannot know what the two keep joking about: it picks
whatever lines it happened to see and the result could be about anyone. So code finds the
evidence first, over the whole chat: the words and short phrases they repeat across many days
(recurring_phrases), and the lines the other person laughed at (laugh_lines). The model reads
those, with the newest part of the chat and a spread of the rest, and decides which are jokes.
Nothing is quoted by the model beyond their own short phrases: the one full message in a read is
the first message of the chat, copied by code.

A read is about a chat between two people. A group chat has no read yet. It is stored with the
upload's digest (encrypted) and goes when the upload is deleted.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from collections import Counter
from datetime import datetime, timedelta, tzinfo
from typing import Any

from agent.matching.style import _EMOJI, _LAUGH
from agent.shared.clock import utc_now_iso
from agent.shared.timeline import message_time, session_gap

# 2: jokes come from phrases the two repeat and lines that got a laugh; a sharper roast.
READ_VERSION = 2
# Fewer messages than this from either side and there is nothing to read.
MIN_MESSAGES_EACH = 10
# A reply slower than this is a new start, not a reply, so it does not count towards reply times.
_REPLY_WINDOW = timedelta(hours=6)
_NIGHT_HOURS = frozenset({0, 1, 2, 3, 4})
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
# What the model reads, at most: lines that got a laugh, lines with a repeated phrase, the newest
# lines, and a spread over everything older.
LAUGH_LINES = 40
PHRASES = 30
PHRASE_EXAMPLES = 3
NEWEST_LINES = 90
SPREAD_LINES = 90
SAMPLE_LINE_CHARS = 160
FIRST_MESSAGE_CHARS = 140
_TEXT_LIMITS = {"headline": 90, "you_two": 340, "roast": 460, "green_flag": 200, "role": 40, "item": 140, "about": 120}
MAX_ITEMS = 4

# A phrase counts as repeated when it is in at least this many messages on this many different days.
_PHRASE_MIN_MESSAGES = 4
_PHRASE_MIN_DAYS = 3
# A word in more than this share of all messages is ordinary talk ("the", "hai", "ok"), found
# from the chat itself so it works in any language mix. A running joke can be said often, so the
# bar is high: only the words that are everywhere are left out.
_COMMON_WORD_SHARE = 0.05
# In a chat with a real vocabulary the most used words are filler in any language ("hai", "the",
# "yaar"), whatever their share; a small made-up chat is judged by share alone.
_FILLER_TOP_WORDS = 30
_REAL_VOCABULARY = 300
# Half the room goes to what got laughs, the rest to what simply comes up most.
_LAUGH_SHARE_OF_ROOM = 0.5
# A word alone needs this many letters to be shown; shorter ones only inside a phrase.
_WORD_ALONE_LETTERS = 4
# A phrase mostly found in the same messages as a stronger one is the same thing said longer.
_SAME_MESSAGES = 0.8
_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?|\d+")
# What masking leaves behind in a stored chat; never a phrase of theirs.
_MASKS = frozenset({"link", "email", "phone"})

CHAT_READ_SYSTEM_PROMPT = """You read a chat between two people and tell them what it is really like, the way a close friend who has read all of it would. One of them uploaded it and will read your answer, and may show it to the other.

Input JSON:
- "me", "them": their names.
- "counts": facts code counted over the whole chat, for each of them.
- "phrases": words and short phrases the two keep repeating, found by code over the whole chat: {"phrase", "times", "days", "me", "them" (how often each said it), "got_laughs" (times the other laughed right after), "lines"}. These are candidates: some are running jokes or nicknames, some are just subjects, some are nothing.
- "lines": [{"n", "who": "me" | "them", "day", "text", "laughed"?}]: part of the chat, oldest first. "laughed": true means the other person laughed right after that line.

Return JSON only:
{"headline": "<one line that sums up the two of them, at most twelve words>",
 "you_two": "<two sentences on what this chat is like>",
 "roles": {"me": "<who they are in this chat, two to four words>", "them": "<the same for the other>"},
 "running_jokes": [{"text": "<the joke, phrase or nickname the way they say it>", "about": "<what it means between them, a few words>", "lines": [<n>, <n>]}],
 "keep_coming_back_to": [{"text": "<a subject they return to, a few words>", "lines": [<n>]}],
 "friction": {"text": "<what they bump on, one sentence>", "lines": [<n>]} | null,
 "green_flag": "<one sentence about something good between them>",
 "roast": "<three short lines: one jab at each of them and one at both>"}

Be specific or say nothing. Every sentence must hold something only these two have: a phrase of theirs, a place, a person, a plan, a habit with its number. A sentence that could be said about any two friends ("warm banter", "they tease each other", "catching up on life") is worthless: cut it.

Running jokes: only what the chat shows is a joke between them. Look in "phrases" (repeated over many days, often with laughs after) and in lines marked "laughed", and read the lines around them to see what the joke is. Write it in their own words, in the language they wrote it in, and say in "about" what it is. Name at least two lines for each. If nothing there is a joke, return an empty list: an invented joke is worse than none.

The roast: tease them the way a close friend in their own group chat would, sharp and specific, with affection underneath. Build each jab on a number from "counts" or a real moment from the lines, and use their own phrases. No compliments inside the roast, no softening ("but it's sweet"), no explaining the joke. Never about looks, body, money, health, religion, caste or family.

Other rules: only what is in the input. Every running joke, subject and friction names the line numbers it comes from. At most four jokes and four subjects; friction is null when the lines do not show one. Plain English for your own words even when they write Hindi or Hinglish, but keep their jokes, nicknames and phrases as they wrote them. Use their names. Leave out anything about health, sex or money even when it is in the lines. This may be shared: tease, but write nothing that would humiliate either of them in front of the other."""

# The same shape as the prompt's "Return JSON", for providers that take a schema (Claude).
_LINES_SCHEMA = {"type": "array", "items": {"type": "integer"}}
_ITEM_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "lines": _LINES_SCHEMA},
    "required": ["text", "lines"],
    "additionalProperties": False,
}
_JOKE_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "about": {"type": "string"}, "lines": _LINES_SCHEMA},
    "required": ["text", "about", "lines"],
    "additionalProperties": False,
}
CHAT_READ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "you_two": {"type": "string"},
        "roles": {"type": "object", "properties": {"me": {"type": "string"}, "them": {"type": "string"}}, "required": ["me", "them"], "additionalProperties": False},
        "running_jokes": {"type": "array", "items": _JOKE_SCHEMA},
        "keep_coming_back_to": {"type": "array", "items": _ITEM_SCHEMA},
        "friction": {"anyOf": [_ITEM_SCHEMA, {"type": "null"}]},
        "green_flag": {"type": "string"},
        "roast": {"type": "string"},
    },
    "required": ["headline", "you_two", "roles", "running_jokes", "keep_coming_back_to", "friction", "green_flag", "roast"],
    "additionalProperties": False,
}


def two_sides(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None, int]:
    """(the messages that have a time and words, the other person's name, how many other people).
    The uploader's lines are role "user"; everyone else is role "other" with their name."""
    kept = [m for m in messages if m.get("role") in {"user", "other"} and str(m.get("content") or "").strip() and message_time(m)]
    speakers = Counter(str(m.get("speaker") or "") for m in kept if m["role"] == "other")
    partner = speakers.most_common(1)[0][0] if speakers else None
    return kept, partner or None, len(speakers)


def _side(message: dict[str, Any]) -> str:
    return "me" if message["role"] == "user" else "them"


def chat_counts(messages: list[dict[str, Any]], zone: tzinfo) -> dict[str, Any]:
    """Everything code can count over a two-person chat. Sides are "me" (the uploader) and "them".
    A message here is a burst: lines one person sent within a few minutes are stored as one."""
    times = [message_time(m).astimezone(zone) for m in messages]  # type: ignore[union-attr]
    per: dict[str, dict[str, Any]] = {who: {"messages": 0, "words": 0, "laughs": 0, "emoji": Counter(), "questions": 0, "night": 0, "starts": 0, "last_words": 0, "double_texts": 0, "replies": []} for who in ("me", "them")}
    days: Counter[str] = Counter()
    hours: Counter[int] = Counter()
    weekdays: Counter[int] = Counter()
    gap = session_gap()
    longest_silence: tuple[timedelta, str | None] = (timedelta(0), None)
    for index, (message, at) in enumerate(zip(messages, times)):
        who, text = _side(message), str(message["content"])
        mine = per[who]
        mine["messages"] += 1
        mine["words"] += len(text.split())
        mine["laughs"] += bool(_LAUGH.search(text))
        mine["emoji"].update(_EMOJI.findall(text))
        mine["questions"] += "?" in text
        mine["night"] += at.hour in _NIGHT_HOURS
        days[at.date().isoformat()] += 1
        hours[at.hour] += 1
        weekdays[at.weekday()] += 1
        if not index:
            mine["starts"] += 1
            continue
        previous, since = messages[index - 1], at - times[index - 1]
        if since >= gap:
            mine["starts"] += 1
            per[_side(previous)]["last_words"] += 1
            if since > longest_silence[0]:
                longest_silence = (since, times[index - 1].date().isoformat())
        elif _side(previous) == who:
            mine["double_texts"] += 1
        elif since <= _REPLY_WINDOW:
            mine["replies"].append(since.total_seconds())
    per[_side(messages[-1])]["last_words"] += 1
    first, last = times[0], times[-1]
    span_days = (last.date() - first.date()).days + 1
    busiest_hour = max(hours, key=lambda hour: hours[hour])
    return {
        "from": first.date().isoformat(),
        "to": last.date().isoformat(),
        "span_days": span_days,
        "days_talked": len(days),
        "longest_streak_days": _longest_streak(sorted(days)),
        "longest_silence_days": longest_silence[0].days,
        "longest_silence_from": longest_silence[1],
        "messages": len(messages),
        "busiest_hour": busiest_hour,
        "busiest_weekday": _WEEKDAYS[max(weekdays, key=lambda day: weekdays[day])],
        "busiest_day": {"date": max(days, key=lambda day: days[day]), "messages": max(days.values())},
        "first_message": {"who": _side(messages[0]), "date": first.date().isoformat(), "text": " ".join(str(messages[0]["content"]).split())[:FIRST_MESSAGE_CHARS]},
        **{
            who: {
                "messages": stats["messages"],
                "words": stats["words"],
                "words_per_message": round(stats["words"] / stats["messages"], 1) if stats["messages"] else 0,
                "starts": stats["starts"],
                "last_words": stats["last_words"],
                "double_texts": stats["double_texts"],
                "reply_median_seconds": round(statistics.median(stats["replies"])) if stats["replies"] else None,
                "laughs": stats["laughs"],
                "questions": stats["questions"],
                "night_messages": stats["night"],
                "top_emoji": [emoji for emoji, _ in stats["emoji"].most_common(3)],
            }
            for who, stats in per.items()
        },
    }


def laugh_lines(messages: list[dict[str, Any]], *, limit: int = LAUGH_LINES) -> list[int]:
    """Lines the other person laughed at: the next message is theirs, soon after, and has a laugh in
    it. Strongest laughs first (more laugh marks and laughing emoji), then the newest; indexes."""
    scored: list[tuple[int, int]] = []
    for index in range(len(messages) - 1):
        line, reply = messages[index], messages[index + 1]
        said = str(line["content"])
        if _side(reply) == _side(line) or (_LAUGH.search(said) and len(said.split()) <= 2):
            continue  # a laugh answering a laugh is not a joke landing
        gap = message_time(reply) - message_time(line)  # type: ignore[operator]
        strength = len(_LAUGH.findall(str(reply["content"])))
        if strength and gap <= _REPLY_WINDOW:
            scored.append((strength, index))
    scored.sort(key=lambda item: (-item[0], -item[1]))
    return sorted(index for _, index in scored[:limit])


def recurring_phrases(messages: list[dict[str, Any]], zone: tzinfo, *, limit: int = PHRASES) -> list[dict[str, Any]]:
    """Words and phrases of one to three words that the two keep saying: in several messages, on
    several days, and not ordinary talk. What is ordinary is measured in the chat itself (a word in
    a large share of all messages), so no word list is needed and any language mix works. Ranked by
    how often the other person laughed right after, then how often and over how many days it came
    up. Candidates for running jokes, nicknames and favourite subjects; the model decides which."""
    total = len(messages)
    if not total:
        return []
    laughed = set(laugh_lines(messages, limit=total))
    per_message: list[list[str]] = []
    word_share: Counter[str] = Counter()
    for message in messages:
        words = [word for word in (found.casefold() for found in _WORD.findall(str(message["content"]))) if word not in _MASKS]
        per_message.append(words)
        word_share.update(set(words))
    common = {word for word, count in word_share.items() if count / total > _COMMON_WORD_SHARE}
    if len(word_share) >= _REAL_VOCABULARY:
        common |= {word for word, _ in word_share.most_common(_FILLER_TOP_WORDS)}

    def worth(gram: tuple[str, ...]) -> bool:
        # Not ordinary talk: a word alone must be a real word that is not everywhere; a phrase
        # needs one such word and must not be filler at both ends ("to the"), which is never the joke.
        if len(gram) == 1:
            return gram[0] not in common and len(gram[0]) >= _WORD_ALONE_LETTERS and not gram[0].isdigit()
        return any(word not in common and len(word) >= 3 for word in gram) and not (gram[0] in common and gram[-1] in common)

    uses: dict[tuple[str, ...], list[int]] = {}
    for index, words in enumerate(per_message):
        seen: set[tuple[str, ...]] = set()
        for size in (1, 2, 3):
            for start in range(len(words) - size + 1):
                gram = tuple(words[start : start + size])
                if gram in seen or not worth(gram):
                    continue
                seen.add(gram)
                uses.setdefault(gram, []).append(index)

    found: list[dict[str, Any]] = []
    for gram, indexes in uses.items():
        if len(indexes) < _PHRASE_MIN_MESSAGES:
            continue
        days = {message_time(messages[i]).astimezone(zone).date().isoformat() for i in indexes}  # type: ignore[union-attr]
        if len(days) < _PHRASE_MIN_DAYS:
            continue
        got_laughs = sum(1 for i in indexes if i in laughed)
        found.append({
            "gram": gram, "indexes": indexes, "days": len(days), "got_laughs": got_laughs,
            "score": (1 + got_laughs) * len(indexes) * math.log(1 + len(days)) * (1 + 0.5 * (len(gram) - 1)),
        })
    kept: list[dict[str, Any]] = []

    def take(ranked: list[dict[str, Any]], room: int) -> None:
        for item in ranked:
            if len(kept) >= room:
                return
            # A phrase and its parts say the same thing ("sharma ji" and "sharma"), and so do pieces
            # of one sentence that is repeated whole: keep the first, the stronger.
            words, where = set(item["gram"]), set(item["indexes"])
            if any(
                words <= set(other["gram"]) or set(other["gram"]) <= words or len(where & set(other["indexes"])) / len(where) >= _SAME_MESSAGES
                for other in kept
            ):
                continue
            kept.append(item)

    # What the other person laughs at first (a joke said nine times beats filler said forty), then
    # what simply comes up most.
    # Ranked by how reliably it gets a laugh, so "ok professor" (a laugh every time) comes before a
    # plain word that happens to sit in the same messages; the longer phrase wins a tie.
    funniest = sorted(
        (item for item in found if item["got_laughs"] >= 2),
        key=lambda item: (-round(item["got_laughs"] / len(item["indexes"]), 1), -item["got_laughs"], -len(item["gram"]), -item["score"]),
    )
    take(funniest, int(limit * _LAUGH_SHARE_OF_ROOM))
    take(sorted(found, key=lambda item: -item["score"]), limit)
    out = []
    for item in kept:
        indexes = item["indexes"]
        funny = [i for i in indexes if i in laughed]
        # Examples to read: where it started, the latest that got a laugh, the latest.
        examples = list(dict.fromkeys([indexes[0], *funny[-1:], indexes[-1], *indexes[1:]]))[:PHRASE_EXAMPLES]
        out.append({
            "phrase": " ".join(item["gram"]),
            "times": len(indexes),
            "days": item["days"],
            "me": sum(1 for i in indexes if _side(messages[i]) == "me"),
            "them": sum(1 for i in indexes if _side(messages[i]) == "them"),
            "got_laughs": item["got_laughs"],
            "lines": sorted(examples),
        })
    return out


def sample_lines(messages: list[dict[str, Any]], zone: tzinfo, *, phrases: list[dict[str, Any]] | None = None, laughs: list[int] | None = None) -> list[dict[str, Any]]:
    """The lines the model reads, numbered by their place in the whole chat: every line that got a
    strong laugh and every phrase's examples (each with the line after it, to see the reaction), the
    newest lines in full, and a spread over everything older so nothing is judged from one month."""
    total = len(messages)
    laughs = laugh_lines(messages) if laughs is None else laughs
    wanted: set[int] = set(range(max(0, total - NEWEST_LINES), total))
    for index in [*laughs, *(n for phrase in phrases or [] for n in phrase["lines"])]:
        wanted.update(i for i in (index, index + 1) if 0 <= i < total)
    older = [i for i in range(max(0, total - NEWEST_LINES)) if i not in wanted]
    if len(older) > SPREAD_LINES:
        step = len(older) / SPREAD_LINES
        older = [older[int(i * step)] for i in range(SPREAD_LINES)]
    wanted.update(older)
    laughed = set(laugh_lines(messages, limit=total))
    return [
        {
            "n": index,
            "who": _side(messages[index]),
            "day": message_time(messages[index]).astimezone(zone).date().isoformat(),  # type: ignore[union-attr]
            "text": " ".join(str(messages[index]["content"]).split())[:SAMPLE_LINE_CHARS],
            **({"laughed": True} if index in laughed else {}),
        }
        for index in sorted(wanted)
    ]


def read_input(me: str, them: str, counts: dict[str, Any], lines: list[dict[str, Any]], phrases: list[dict[str, Any]] | None = None) -> str:
    shown = {key: value for key, value in counts.items() if key != "first_message"}
    return json.dumps({"me": me, "them": them, "counts": shown, "phrases": phrases or [], "lines": lines}, ensure_ascii=False)


def validate_written(raw: Any, shown: set[int]) -> dict[str, Any]:
    """Keep what the sample supports: bounded text, jokes and subjects only with lines the model
    was shown (a joke needs two), friction only with a line. Anything else is dropped."""
    data = raw if isinstance(raw, dict) else {}

    def text(value: Any, kind: str) -> str:
        return _fit(" ".join(value.split()), _TEXT_LIMITS[kind]) if isinstance(value, str) else ""

    def lines_of(item: Any) -> list[int]:
        cited = item.get("lines") if isinstance(item, dict) else None
        return sorted({n for n in cited or [] if isinstance(n, int) and not isinstance(n, bool) and n in shown})

    def items(key: str, need: int, *, about: bool = False) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in data.get(key) or []:
            words, cited = text(item.get("text") if isinstance(item, dict) else None, "item"), lines_of(item)
            if words and len(cited) >= need and words.casefold() not in {existing["text"].casefold() for existing in out}:
                meaning = text(item.get("about"), "about") if about else ""
                out.append({"text": words, **({"about": meaning} if meaning else {}), "lines": cited})
            if len(out) == MAX_ITEMS:
                break
        return out

    roles = data.get("roles") if isinstance(data.get("roles"), dict) else {}
    friction = data.get("friction")
    friction_text, friction_lines = text(friction.get("text") if isinstance(friction, dict) else None, "you_two"), lines_of(friction)
    return {
        "headline": text(data.get("headline"), "headline"),
        "you_two": text(data.get("you_two"), "you_two"),
        "roles": {"me": text(roles.get("me"), "role"), "them": text(roles.get("them"), "role")},
        "running_jokes": items("running_jokes", 2, about=True),
        "keep_coming_back_to": items("keep_coming_back_to", 1),
        "friction": {"text": friction_text, "lines": friction_lines} if friction_text and friction_lines else None,
        "green_flag": text(data.get("green_flag"), "green_flag"),
        "roast": text(data.get("roast"), "roast"),
    }


async def build_chat_read(messages: list[dict[str, Any]], *, me: str, zone: tzinfo, conversation_id: str, model: str | None = None) -> dict[str, Any]:
    """The whole read for one stored upload. {"state": "ready", ...} or why there is none:
    "group_chat", or "too_short" when either side wrote too little. The counts stand on their
    own: when the model call fails the read is still ready, with "written" null."""
    from agent.providers import write_chat_read

    kept, partner, others = two_sides(messages)
    if others > 1:
        return {"state": "group_chat"}
    mine = sum(1 for m in kept if m["role"] == "user")
    if partner is None or mine < MIN_MESSAGES_EACH or len(kept) - mine < MIN_MESSAGES_EACH:
        return {"state": "too_short"}
    counts = chat_counts(kept, zone)
    phrases = recurring_phrases(kept, zone)
    lines = sample_lines(kept, zone, phrases=phrases)
    them = partner.split()[0]
    written = None
    try:
        raw = await write_chat_read(read_input(me, them, counts, lines, phrases), conversation_id=conversation_id, model=model)
        checked = validate_written(raw, {line["n"] for line in lines})
        written = checked if checked["headline"] or checked["roast"] or checked["you_two"] else None
    except Exception:  # the numbers are still worth showing
        written = None
    return {"state": "ready", "version": READ_VERSION, "me": me, "them": them, "counts": counts, "written": written, "built_at": utc_now_iso()}


def _fit(text: str, limit: int) -> str:
    """Text that is too long ends at its last whole sentence that fits, else at a whole word with
    a mark; never in the middle of a word."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    sentence = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if sentence >= limit // 2:
        return cut[: sentence + 1]
    return cut[: cut.rfind(" ")].rstrip(",;:") + "…" if " " in cut else cut


def _longest_streak(days: list[str]) -> int:
    best = run = 0
    previous = None
    for day in days:
        date = datetime.fromisoformat(day).date()
        run = run + 1 if previous and (date - previous).days == 1 else 1
        best = max(best, run)
        previous = date
    return best


__all__ = [
    "CHAT_READ_SCHEMA",
    "CHAT_READ_SYSTEM_PROMPT",
    "MIN_MESSAGES_EACH",
    "READ_VERSION",
    "build_chat_read",
    "chat_counts",
    "laugh_lines",
    "read_input",
    "recurring_phrases",
    "sample_lines",
    "two_sides",
    "validate_written",
]
