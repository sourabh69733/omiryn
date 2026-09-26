"""A dated one-line log per chat session, written by background cognition.

Code decides where sessions start and end (a silence of AGENT_SESSION_GAP_HOURS), so the log
keys are stable across batches. The model only writes what each session was about and what
was left unfinished. Replies read the last few entries, which answers "what were we doing
last time?" or "what did we talk about on Monday?" from the same general record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agent.shared.timeline import parse_time, session_gap

from .models import MemoryBatch, SessionLogEntry

MAX_SESSION_LOG_ENTRIES = 20
MAX_SESSION_GIST_CHARS = 240
MAX_SESSION_UNFINISHED_CHARS = 160


@dataclass(frozen=True)
class BatchSession:
    """One session touched by a batch; `id` is the short label the model sees."""

    id: str
    started_at: str
    has_new_messages: bool
    last_new_message_at: str | None


def batch_sessions(
    batch: MemoryBatch, log: tuple[SessionLogEntry, ...]
) -> tuple[dict[int, str], list[BatchSession]]:
    """Map each timed batch message to a session label, continuing the last logged session
    when the batch picks up within the session gap."""
    labels: dict[int, str] = {}
    starts: dict[str, str] = {}
    new_times: dict[str, datetime] = {}
    last = log[-1] if log else None
    key: str | None = None
    previous: datetime | None = None
    for message in sorted(batch.messages, key=lambda item: item.message_index):
        sent = parse_time(message.sent_at)
        if sent is None:
            continue
        if previous is None:
            key = _continued_key(last, sent) or sent.isoformat()
        elif sent - previous >= session_gap():
            key = sent.isoformat()
        previous = sent
        label = starts.setdefault(key, f"s{len(starts) + 1}") if key else None
        if label is None:
            continue
        labels[message.message_index] = label
        if message.scope == "new":
            new_times[label] = max(new_times.get(label, sent), sent)
    by_label = {label: start for start, label in starts.items()}
    sessions = [
        BatchSession(
            id=label,
            started_at=by_label[label],
            has_new_messages=label in new_times,
            last_new_message_at=new_times[label].isoformat() if label in new_times else None,
        )
        for label in sorted(by_label, key=lambda item: int(item[1:]))
    ]
    return labels, sessions


def merge_session_log(
    raw: Any,
    *,
    batch: MemoryBatch,
    previous: tuple[SessionLogEntry, ...],
) -> tuple[SessionLogEntry, ...]:
    """Apply the model's entries for sessions with new messages; bad items are dropped."""
    if not isinstance(raw, list):
        return previous
    _, sessions = batch_sessions(batch, previous)
    writable = {session.id: session for session in sessions if session.has_new_messages}
    entries = {entry.started_at: entry for entry in previous}
    for item in raw:
        if not isinstance(item, dict) or item.get("session") not in writable:
            continue
        gist = _clean(item.get("gist"), MAX_SESSION_GIST_CHARS)
        if not gist:
            continue
        session = writable[str(item["session"])]
        earlier = entries.get(session.started_at)
        entries[session.started_at] = SessionLogEntry(
            started_at=session.started_at,
            ended_at=_latest(earlier.ended_at if earlier else None, session.last_new_message_at),
            gist=gist,
            unfinished=_clean(item.get("unfinished"), MAX_SESSION_UNFINISHED_CHARS),
        )
    ordered = sorted(entries.values(), key=lambda entry: parse_time(entry.started_at) or datetime.min)
    return tuple(ordered[-MAX_SESSION_LOG_ENTRIES:])


def session_log_from_raw(raw: Any) -> tuple[SessionLogEntry, ...]:
    """Rebuild stored entries; malformed ones are skipped."""
    entries = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and parse_time(item.get("started_at")) and item.get("gist"):
            entries.append(
                SessionLogEntry(
                    started_at=str(item["started_at"]),
                    ended_at=str(item.get("ended_at") or item["started_at"]),
                    gist=str(item["gist"]),
                    unfinished=str(item.get("unfinished") or ""),
                )
            )
    return tuple(entries[-MAX_SESSION_LOG_ENTRIES:])


def _continued_key(last: SessionLogEntry | None, sent: datetime) -> str | None:
    if last is None:
        return None
    started, ended = parse_time(last.started_at), parse_time(last.ended_at)
    if started and ended and started <= sent and sent - ended < session_gap():
        return last.started_at
    return None


def _latest(first: str | None, second: str | None) -> str:
    times = [value for value in (first, second) if parse_time(value)]
    return max(times, key=lambda value: parse_time(value)) if times else ""


def _clean(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split()) if isinstance(value, str) else ""
    return text[:limit]


__all__ = [
    "BatchSession",
    "batch_sessions",
    "merge_session_log",
    "session_log_from_raw",
]
