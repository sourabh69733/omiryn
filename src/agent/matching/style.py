"""How a person writes to Omi, as counts, and what two people's counts say about a pair.

Nothing here is a judgment. Code counts a user's own messages (length, questions, laughs, emoji,
language mix, the hours they write, how fast they come back, who opens a session) and turns two
users' counts into a few plain lines the match judge reads as compatibility facts: "both write
mostly Hinglish", "both active after 9 pm", "A writes short, B long". No line is ever shown to a
user, and nothing from the other person's chats leaves the pack.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from datetime import datetime, tzinfo
from typing import Any

from agent.shared.timeline import message_time, session_gap

STYLE_VERSION = 1
# Fewer messages than this and the counts say little; pair lines are not written.
MIN_MESSAGES = 30
SHORT_CHARS = 30
LONG_CHARS = 120
# A message with one of these is a laugh in text.
_LAUGH = re.compile(r"(?:\bha(?:ha)+\b|\bhe(?:he)+\b|\blol+\b|\blmao\b|\brofl\b|\bxd\b|😂|🤣|😆|💀)", re.IGNORECASE)
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
# Romanised Hindi function words: a message with two of them, or one in a short message, is
# Hinglish. Function words, not topic words, so the list is about how people write, not what they
# write about; words that are also common English ("the", "main", "par") are left out.
_HINDI_WORDS = frozenset(
    "hai hain nahi nhi kya kyu kyun yaar yar bhi kar karo kiya toh mera meri tera teri aur abhi kuch acha accha "
    "haan haa matlab bas tha thi ho hoga hogi ka ki ke mujhe tujhe bahut bohot bhai thik theek chal chalo "
    "mai hum tum aap woh yeh ye kab kaha kahan kaise kaisa kaisi lekin phir fir sab".split()
)
_WORD = re.compile(r"[a-z]+")
# Local hours grouped into bands for the pair lines.
_BANDS = (("morning", range(5, 12)), ("day", range(12, 17)), ("evening", range(17, 22)), ("night", (22, 23, 0, 1, 2, 3, 4)))
# Share of a person's messages an hour needs to count as one of their usual hours.
_ACTIVE_HOUR_SHARE = 0.06
_QUICK_REPLY_SECONDS = 60
_SLOW_REPLY_SECONDS = 300
_OFTEN = 0.15
_RARELY = 0.03
_MOSTLY = 0.5


def style_counts(conversations: list[dict[str, Any]], zone: tzinfo) -> dict[str, Any]:
    """Counts over a user's own messages in their chats with Omi (temporary chats excluded)."""
    chars: list[int] = []
    words: list[int] = []
    questions = laughs = emoji = devanagari = hinglish = 0
    hours: Counter[int] = Counter()
    gaps: list[float] = []
    reply_lags: list[float] = []
    sessions = opened_by_user = 0
    days: set[str] = set()
    gap = session_gap()
    for conversation in conversations:
        if conversation.get("temporary"):
            continue
        messages = [m for m in conversation.get("messages") or [] if m.get("role") in {"user", "assistant"}]
        last_time: datetime | None = None
        last_user_time: datetime | None = None
        last_assistant_time: datetime | None = None
        for message in messages:
            at = message_time(message)
            if at is None:
                continue
            new_session = last_time is None or at - last_time >= gap
            if new_session:
                sessions += 1
                if message.get("role") == "user":
                    opened_by_user += 1
                last_user_time = last_assistant_time = None
            last_time = at
            if message.get("role") == "assistant":
                last_assistant_time = at
                continue
            text = str(message.get("content") or "")
            if not text.strip():
                continue
            chars.append(len(text))
            words.append(len(text.split()))
            questions += "?" in text
            laughs += bool(_LAUGH.search(text))
            emoji += bool(_EMOJI.search(text))
            if _DEVANAGARI.search(text):
                devanagari += 1
            else:
                latin = _WORD.findall(text.lower())
                hindi = sum(1 for word in latin if word in _HINDI_WORDS)
                if hindi >= 2 or (hindi == 1 and len(latin) <= 4):
                    hinglish += 1
            local = at.astimezone(zone)
            hours[local.hour] += 1
            days.add(local.date().isoformat())
            if last_user_time is not None:
                gaps.append((at - last_user_time).total_seconds())
            if last_assistant_time is not None and (last_user_time is None or last_assistant_time > last_user_time):
                reply_lags.append((at - last_assistant_time).total_seconds())
            last_user_time = at
    total = len(chars)
    share = lambda count: round(count / total, 3) if total else 0.0  # noqa: E731
    return {
        "version": STYLE_VERSION,
        "message_count": total,
        "days": len(days),
        "chars_median": statistics.median(chars) if chars else 0,
        "words_mean": round(statistics.fmean(words), 1) if words else 0.0,
        "short_share": share(sum(1 for c in chars if c <= SHORT_CHARS)),
        "long_share": share(sum(1 for c in chars if c >= LONG_CHARS)),
        "question_share": share(questions),
        "laugh_share": share(laughs),
        "emoji_share": share(emoji),
        "devanagari_share": share(devanagari),
        "hinglish_share": share(hinglish),
        "english_share": share(total - devanagari - hinglish),
        "hours": {str(hour): share(count) for hour, count in sorted(hours.items())},
        "gap_median_seconds": round(statistics.median(gaps)) if gaps else None,
        "reply_lag_median_seconds": round(statistics.median(reply_lags)) if reply_lags else None,
        "sessions": sessions,
        "opened_by_user_share": round(opened_by_user / sessions, 3) if sessions else 0.0,
    }


def enough(counts: dict[str, Any] | None) -> bool:
    return bool(counts) and int(counts.get("message_count") or 0) >= MIN_MESSAGES


def hindi_share(counts: dict[str, Any]) -> float:
    return float(counts.get("devanagari_share") or 0) + float(counts.get("hinglish_share") or 0)


def active_hours(counts: dict[str, Any]) -> frozenset[int]:
    return frozenset(int(hour) for hour, share in (counts.get("hours") or {}).items() if float(share) >= _ACTIVE_HOUR_SHARE)


def bands_of(hours: frozenset[int]) -> tuple[str, ...]:
    """The named parts of the day a set of hours falls in, most-covered first."""
    counts = {name: sum(1 for hour in hours if hour in band) for name, band in _BANDS}
    return tuple(name for name, count in sorted(counts.items(), key=lambda item: -item[1]) if count)


def pair_style_lines(a: dict[str, Any], b: dict[str, Any], name_a: str, name_b: str) -> list[str]:
    """Plain lines on how the two write, for the judge. Empty when either has too few messages."""
    if not enough(a) or not enough(b):
        return []
    lines: list[str] = []
    ha, hb = hindi_share(a), hindi_share(b)
    if ha >= _MOSTLY and hb >= _MOSTLY:
        lines.append("both write mostly Hinglish")
    elif ha < _MOSTLY and hb < _MOSTLY:
        lines.append("both write mostly English")
    else:
        hing, eng = (name_a, name_b) if ha >= _MOSTLY else (name_b, name_a)
        lines.append(f"{hing} writes mostly Hinglish, {eng} mostly English")
    hours_a, hours_b = active_hours(a), active_hours(b)
    shared = hours_a & hours_b
    if hours_a and hours_b:
        if len(shared) / len(hours_a | hours_b) >= 0.5:
            lines.append(f"both usually write in the {' and '.join(bands_of(frozenset(shared))[:2])}")
        elif shared:
            lines.append(f"their usual hours overlap a little, in the {bands_of(frozenset(shared))[0]}")
        else:
            lines.append(f"{name_a} usually writes in the {bands_of(hours_a)[0]}, {name_b} in the {bands_of(hours_b)[0]}; their hours do not overlap")
    la, lb = _length(a), _length(b)
    if la == lb and la != "medium":
        lines.append(f"both write {la} messages")
    elif la != lb and "medium" not in (la, lb):
        lines.append(f"{name_a} writes {la}, {name_b} writes {lb}")
    ga, gb = float(a.get("laugh_share") or 0), float(b.get("laugh_share") or 0)
    if ga >= _OFTEN and gb >= _OFTEN:
        lines.append("both laugh in text often")
    elif (ga >= _OFTEN and gb <= _RARELY) or (gb >= _OFTEN and ga <= _RARELY):
        often, rarely = (name_a, name_b) if ga > gb else (name_b, name_a)
        lines.append(f"{often} laughs in text a lot, {rarely} rarely")
    ra, rb = _reply(a), _reply(b)
    if ra == rb and ra:
        lines.append(f"both come back {ra}")
    elif ra and rb:
        lines.append(f"{name_a} comes back {ra}, {name_b} {rb}")
    oa, ob = float(a.get("opened_by_user_share") or 0), float(b.get("opened_by_user_share") or 0)
    if oa >= 0.7 and ob >= 0.7:
        lines.append("both usually start the conversation themselves")
    elif (oa >= 0.7 and ob <= 0.4) or (ob >= 0.7 and oa <= 0.4):
        starts, waits = (name_a, name_b) if oa > ob else (name_b, name_a)
        lines.append(f"{starts} usually starts the conversation, {waits} waits to be nudged")
    return lines


def style_gaps(a: dict[str, Any], b: dict[str, Any]) -> tuple[str, ...]:
    """Hard gaps the pick may treat as filters: no common language, no common hours."""
    if not enough(a) or not enough(b):
        return ()
    gaps: list[str] = []
    ha, hb = hindi_share(a), hindi_share(b)
    if (ha >= 0.7 and hb <= 0.1) or (hb >= 0.7 and ha <= 0.1):
        gaps.append("language")
    hours_a, hours_b = active_hours(a), active_hours(b)
    if hours_a and hours_b and not hours_a & hours_b:
        gaps.append("hours")
    return tuple(gaps)


def _length(counts: dict[str, Any]) -> str:
    median = float(counts.get("chars_median") or 0)
    return "short" if median <= 40 else "long" if median >= 90 else "medium"


def _reply(counts: dict[str, Any]) -> str | None:
    lag = counts.get("reply_lag_median_seconds")
    if lag is None:
        return None
    return "within a minute" if lag <= _QUICK_REPLY_SECONDS else "after a while" if lag >= _SLOW_REPLY_SECONDS else None


def rebuild_user_style(user_id: str) -> dict[str, Any]:
    """Count the user's chats and store the result; returns the counts."""
    from agent.shared.timeline import user_zone
    from storage import get_user_timezone, list_conversations, set_user_style

    counts = style_counts(list_conversations(user_id), user_zone(get_user_timezone(user_id)))
    set_user_style(user_id, counts)
    return counts


__all__ = [
    "MIN_MESSAGES",
    "STYLE_VERSION",
    "active_hours",
    "bands_of",
    "enough",
    "pair_style_lines",
    "rebuild_user_style",
    "style_counts",
    "style_gaps",
]
