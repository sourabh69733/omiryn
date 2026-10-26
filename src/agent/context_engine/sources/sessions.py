"""The last few chat sessions, one dated line each, from the background session log."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent.config import agent_pipeline_config
from agent.memory_engine.processing.service import get_processing_state
from agent.shared.clock import utc_now
from agent.shared.timeline import clock_label, humanize_gap, local_label, parse_time, session_gap, user_zone
from storage import get_user_timezone

RECENT_SESSIONS_SOURCE_TYPE = "recent_sessions"
RECENT_SESSION_LIMIT = 5


def recent_sessions_sources(conversation_id: str, user_id: str | None) -> list[dict[str, Any]]:
    """The last few chat sessions, one dated line each, from the background session log."""
    if not user_id or agent_pipeline_config().memory_contract_version != 3:
        return []
    state = get_processing_state(conversation_id, user_id)
    entries = state.handoff.session_log[-RECENT_SESSION_LIMIT:] if state else ()
    if not entries:
        return []
    now = utc_now()
    zone = user_zone(get_user_timezone(user_id))
    lines = ["Your recent chat sessions with the user, oldest first (start to end time):"]
    for entry in entries:
        started, ended = parse_time(entry.started_at), parse_time(entry.ended_at)
        if started is None:
            continue
        current = ended is not None and now - ended < session_gap()
        span = session_span(started, ended, zone)
        when = "this session so far" if current else f"ended {humanize_gap(now - (ended or started))} ago"
        line = f"- {span} ({when}): {entry.gist}"
        # No "left open" note: the model kept filling it with its own follow-ups ("awaiting input
        # on <subject>"), which brought settled topics back. Real loose ends reach the reply anyway:
        # promises (self notes), open questions, threads, and the last session's tail in the history.
        lines.append(line)
    return [
        {
            "source_type": RECENT_SESSIONS_SOURCE_TYPE,
            "title": "Recent sessions",
            "content": "\n".join(lines),
            "metadata": {"session_count": len(lines) - 1},
        }
    ]


def session_span(started: datetime, ended: datetime | None, zone: Any) -> str:
    """'Saturday 26 Sep, 5:11 pm to 10:18 pm': a session is a stretch of time, not a moment."""
    start = started.astimezone(zone)
    if ended is None or ended <= started:
        return local_label(start)
    end = ended.astimezone(zone)
    end_text = clock_label(end) if end.date() == start.date() else local_label(end)
    return f"{local_label(start)} to {end_text}"


__all__ = ["RECENT_SESSIONS_SOURCE_TYPE", "recent_sessions_sources", "session_span"]
