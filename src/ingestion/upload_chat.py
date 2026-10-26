"""Turns an upload into a hidden chat that background memory reads like any other chat.

A WhatsApp export keeps its real times, so sessions, dates and "when they said it" stay true.
The user's own lines are role "user" (the only lines that can prove a memory); everyone else's
are role "other" with their name, as context only. Quick bursts from one person are merged into
one message, and links, emails and phone numbers are masked. Up to MAX_UPLOAD_MESSAGES (the newest)
are stored, so search can find things said months ago; reading the upload for memories and its
digest covers only the newest part (see agent.cognition.background.uploads.read).
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .whatsapp import MEDIA_MARKERS, _redact_private_text, _select_sender, parse_whatsapp_export

# Messages kept from one upload (after merging bursts), newest first: months of a busy chat.
MAX_UPLOAD_MESSAGES = 5000
# Lines from one sender this close together are one message.
BURST_GAP = timedelta(minutes=5)
MESSAGE_CHARS = 800
NOTES_MAX_PARTS = 30
NOTES_MAX_CHARS = 12000

_DATE = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})")
_TIME = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([APap])?\.?[Mm]?\.?")


def whatsapp_upload_messages(export_text: str, user_sender: str | None, zone: ZoneInfo) -> list[dict[str, Any]]:
    """The export as chat messages, oldest first. Raises ValueError for an unknown sender."""
    parsed = [
        message
        for message in parse_whatsapp_export(export_text.replace("\u200e", ""))
        if message.content.strip() and message.content.strip().lower() not in MEDIA_MARKERS
    ]
    if not parsed:
        raise ValueError("That doesn't look like a WhatsApp chat export.")
    me = _select_sender(Counter(message.sender for message in parsed), user_sender)
    day_first = _day_first([message.timestamp_text or "" for message in parsed])
    merged: list[dict[str, Any]] = []
    for message in parsed:
        sent = _parse_time(message.timestamp_text, day_first, zone)
        text = _redact_private_text(message.content.strip())
        role = "user" if message.sender == me else "other"
        last = merged[-1] if merged else None
        if (
            last
            and last["role"] == role
            and last.get("speaker") == (None if role == "user" else message.sender)
            and sent is not None
            and last["_sent"] is not None
            and sent - last["_sent"] <= BURST_GAP
        ):
            last["content"] = f"{last['content']}\n{text}"[:MESSAGE_CHARS]
            last["_sent"] = sent
            continue
        merged.append(
            {
                "role": role,
                **({"speaker": message.sender} if role == "other" else {}),
                "content": text[:MESSAGE_CHARS],
                "imported": True,
                "_sent": sent,
            }
        )
    if not any(item["role"] == "user" for item in merged):
        raise ValueError("None of the messages in this export are yours.")
    start = max(0, len(merged) - MAX_UPLOAD_MESSAGES)
    # Keep the other person's line just before the window, so the first kept reply has what it answers.
    if start and merged[start - 1]["role"] == "other":
        start -= 1
    kept = merged[start:]
    return [_finish(item) for item in kept]


def notes_upload_messages(text: str, now: datetime) -> list[dict[str, Any]]:
    """Notes the user wrote about themselves, as their own messages sent now, one per paragraph."""
    parts = [part.strip() for part in re.split(r"\n\s*\n", text[:NOTES_MAX_CHARS]) if part.strip()]
    if not parts:
        raise ValueError("Nothing to learn from in that text.")
    sent = now.isoformat()
    return [
        {"role": "user", "content": _redact_private_text(part)[:MESSAGE_CHARS], "imported": True, "created_at": sent}
        for part in parts[:NOTES_MAX_PARTS]
    ]


def _finish(item: dict[str, Any]) -> dict[str, Any]:
    sent = item.pop("_sent")
    return {**item, **({"created_at": sent.isoformat()} if sent else {})}


def _day_first(stamps: list[str]) -> bool:
    """WhatsApp writes dates in the phone's order; a part above 12 tells which is the day."""
    for stamp in stamps:
        match = _DATE.search(stamp)
        if not match:
            continue
        first, second = int(match.group(1)), int(match.group(2))
        if first > 12:
            return True
        if second > 12:
            return False
    return True


def _parse_time(stamp: str | None, day_first: bool, zone: ZoneInfo) -> datetime | None:
    if not stamp:
        return None
    date, time = _DATE.search(stamp), _TIME.search(stamp.split(" ", 1)[-1] if " " in stamp else "")
    if not date or not time:
        return None
    first, second, year = int(date.group(1)), int(date.group(2)), int(date.group(3))
    day, month = (first, second) if day_first else (second, first)
    year += 2000 if year < 100 else 0
    hour, minute = int(time.group(1)), int(time.group(2))
    marker = (time.group(4) or "").lower()
    if marker == "p" and hour < 12:
        hour += 12
    elif marker == "a" and hour == 12:
        hour = 0
    try:
        return datetime(year, month, day, hour, minute, tzinfo=zone)
    except ValueError:
        return None


__all__ = ["MAX_UPLOAD_MESSAGES", "notes_upload_messages", "whatsapp_upload_messages"]
