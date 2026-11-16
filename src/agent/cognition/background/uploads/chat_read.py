"""The read: what an uploaded chat says about the two people in it.

Two halves. Code counts what can be counted from the stored chat: how long, how often, who writes
first, who answers faster, who writes more, who laughs, who is up at night. One model call writes
what cannot be counted (the running jokes, what they keep coming back to, where they rub, a short
roast) from a sample of the real lines, naming the lines it means; code keeps an item only when
those lines exist. Nothing is quoted by the model: the one quote in a read is the first message
of the chat, copied by code.

A read is about a chat between two people. A group chat has no read yet. It is stored with the
upload's digest (encrypted) and goes when the upload is deleted.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from datetime import datetime, timedelta, tzinfo
from typing import Any

from agent.matching.style import _EMOJI, _LAUGH
from agent.shared.clock import utc_now_iso
from agent.shared.timeline import message_time, session_gap

READ_VERSION = 1
# Fewer messages than this from either side and there is nothing to read.
MIN_MESSAGES_EACH = 10
# A reply slower than this is a new start, not a reply, so it does not count towards reply times.
_REPLY_WINDOW = timedelta(hours=6)
_NIGHT_HOURS = frozenset({0, 1, 2, 3, 4})
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
# What the model reads: this many lines, the newest half and the rest spread over the whole chat.
SAMPLE_LINES = 260
SAMPLE_LINE_CHARS = 160
FIRST_MESSAGE_CHARS = 140
_TEXT_LIMITS = {"headline": 90, "you_two": 260, "roast": 280, "green_flag": 180, "role": 40, "item": 140}
MAX_ITEMS = 3

CHAT_READ_SYSTEM_PROMPT = """You read a chat between two people and tell them, warmly and honestly, what it is like. One of them uploaded it and will read your answer, and may show it to the other.

Input JSON: {"me": "<their name>", "them": "<the other's name>", "counts": {...}, "lines": [{"n", "who": "me" | "them", "day", "text"}]}.
"lines" is a sample of the chat, oldest first. "counts" are facts code counted over the whole chat; do not repeat them, they are shown next to your words.

Return JSON only:
{"headline": "<one line that sums up the two of them, at most twelve words>",
 "you_two": "<two sentences on what this chat is like>",
 "roles": {"me": "<who they are in this chat, two to four words>", "them": "<the same for the other>"},
 "running_jokes": [{"text": "<the joke or phrase, a few words>", "lines": [<n>, <n>]}],
 "keep_coming_back_to": [{"text": "<a subject they return to, a few words>", "lines": [<n>]}],
 "friction": {"text": "<what they bump on, one sentence>", "lines": [<n>]} | null,
 "green_flag": "<one warm sentence about something good between them>",
 "roast": "<two sentences teasing both of them, never cruel>"}

Rules: only what is in the lines. Every running joke, subject and friction names the line numbers it comes from; a joke needs at least two. At most three jokes and three subjects; leave a list empty or friction null when the lines do not show one. Describe in your own words, in plain English even when they write Hindi or Hinglish; you may use a word or short phrase of theirs for a joke, never a whole message. Use their names. Tease about habits (late replies, long voice-note energy, one-word answers), never about looks, body, money, health, religion, caste or family. Leave out anything about health, sex or money even when it is in the lines. This may be shared: write nothing either of them would mind the other reading."""


def two_sides(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None, int]:
    """(the messages that have a time and words, the other person's name, how many other people).
    The uploader's lines are role "user"; everyone else is role "other" with their name."""
    kept = [m for m in messages if m.get("role") in {"user", "other"} and str(m.get("content") or "").strip() and message_time(m)]
    speakers = Counter(str(m.get("speaker") or "") for m in kept if m["role"] == "other")
    partner = speakers.most_common(1)[0][0] if speakers else None
    return kept, partner or None, len(speakers)


def chat_counts(messages: list[dict[str, Any]], zone: tzinfo) -> dict[str, Any]:
    """Everything code can count over a two-person chat. Sides are "me" (the uploader) and "them".
    A message here is a burst: lines one person sent within a few minutes are stored as one."""
    side = lambda m: "me" if m["role"] == "user" else "them"  # noqa: E731
    times = [message_time(m).astimezone(zone) for m in messages]  # type: ignore[union-attr]
    per: dict[str, dict[str, Any]] = {who: {"messages": 0, "words": 0, "laughs": 0, "emoji": Counter(), "questions": 0, "night": 0, "starts": 0, "last_words": 0, "double_texts": 0, "replies": []} for who in ("me", "them")}
    days: Counter[str] = Counter()
    hours: Counter[int] = Counter()
    weekdays: Counter[int] = Counter()
    gap = session_gap()
    longest_silence = (timedelta(0), None)
    for index, (message, at) in enumerate(zip(messages, times)):
        who, text = side(message), str(message["content"])
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
        previous = messages[index - 1] if index else None
        since = at - times[index - 1] if index else None
        if previous is None or since >= gap:  # type: ignore[operator]
            mine["starts"] += 1
            if previous is not None:
                per[side(previous)]["last_words"] += 1
                if since > longest_silence[0]:  # type: ignore[operator]
                    longest_silence = (since, times[index - 1].date().isoformat())  # type: ignore[assignment]
        elif side(previous) == who:
            mine["double_texts"] += 1
        elif since <= _REPLY_WINDOW:  # type: ignore[operator]
            mine["replies"].append(since.total_seconds())  # type: ignore[union-attr]
    per[side(messages[-1])]["last_words"] += 1
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
        "first_message": {"who": side(messages[0]), "date": first.date().isoformat(), "text": " ".join(str(messages[0]["content"]).split())[:FIRST_MESSAGE_CHARS]},
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


def sample_lines(messages: list[dict[str, Any]], zone: tzinfo, *, limit: int = SAMPLE_LINES) -> list[dict[str, Any]]:
    """The lines the model reads, numbered by their place in the whole chat: the newest half of the
    room in full, the rest spread evenly over everything older, so old jokes can still be seen."""
    indexes = list(range(len(messages)))
    if len(indexes) > limit:
        recent = indexes[-(limit // 2):]
        older = indexes[: -(limit // 2)]
        step = len(older) / (limit - len(recent))
        indexes = sorted({older[int(i * step)] for i in range(limit - len(recent))}) + recent
    return [
        {
            "n": index,
            "who": "me" if messages[index]["role"] == "user" else "them",
            "day": message_time(messages[index]).astimezone(zone).date().isoformat(),  # type: ignore[union-attr]
            "text": " ".join(str(messages[index]["content"]).split())[:SAMPLE_LINE_CHARS],
        }
        for index in indexes
    ]


def read_input(me: str, them: str, counts: dict[str, Any], lines: list[dict[str, Any]]) -> str:
    shown = {key: value for key, value in counts.items() if key != "first_message"}
    return json.dumps({"me": me, "them": them, "counts": shown, "lines": lines}, ensure_ascii=False)


def validate_written(raw: Any, shown: set[int]) -> dict[str, Any]:
    """Keep what the sample supports: bounded text, jokes and subjects only with lines the model
    was shown (a joke needs two), friction only with a line. Anything else is dropped."""
    data = raw if isinstance(raw, dict) else {}

    def text(value: Any, kind: str) -> str:
        return " ".join(str(value).split())[: _TEXT_LIMITS[kind]] if isinstance(value, str) else ""

    def lines_of(item: Any) -> list[int]:
        cited = item.get("lines") if isinstance(item, dict) else None
        return sorted({n for n in cited or [] if isinstance(n, int) and not isinstance(n, bool) and n in shown})

    def items(key: str, need: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in data.get(key) or []:
            words, cited = text(item.get("text") if isinstance(item, dict) else None, "item"), lines_of(item)
            if words and len(cited) >= need and words.casefold() not in {existing["text"].casefold() for existing in out}:
                out.append({"text": words, "lines": cited})
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
        "running_jokes": items("running_jokes", 2),
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
    lines = sample_lines(kept, zone)
    them = partner.split()[0]
    written = None
    try:
        raw = await write_chat_read(read_input(me, them, counts, lines), conversation_id=conversation_id, model=model)
        checked = validate_written(raw, {line["n"] for line in lines})
        written = checked if checked["headline"] or checked["roast"] or checked["you_two"] else None
    except Exception:  # the numbers are still worth showing
        written = None
    return {"state": "ready", "version": READ_VERSION, "me": me, "them": them, "counts": counts, "written": written, "built_at": utc_now_iso()}


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
    "CHAT_READ_SYSTEM_PROMPT",
    "MIN_MESSAGES_EACH",
    "READ_VERSION",
    "build_chat_read",
    "chat_counts",
    "read_input",
    "sample_lines",
    "two_sides",
    "validate_written",
]
