#!/usr/bin/env python3
"""Measure the hand-picked agent numbers against real usage and suggest better defaults.

Reads model-call timings and message times from the database (counts and timings only; no
message text is printed). Nothing is changed: update settings or code defaults from the output.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy import select  # noqa: E402

from agent.cognition.background.service import _timeout_seconds as background_timeout  # noqa: E402
from agent.context_engine.conversation_engine.policy.replies import MAX_REPLY_PARTS  # noqa: E402
from agent.observability.tuning import (  # noqa: E402
    bubble_report,
    call_report,
    pause_report,
    suggested_timeout,
)
from agent.providers.companion.service import reply_timeout_seconds  # noqa: E402
from agent.shared.clock import utc_now  # noqa: E402
from agent.shared.timeline import session_gap, time_note_gap  # noqa: E402
from storage import get_conversation  # noqa: E402
from storage.database import ENGINE  # noqa: E402
from storage.schema import agent_conversations, agent_usage_events  # noqa: E402


def _fmt(value: float | None, unit: str = "") -> str:
    return "-" if value is None else f"{value:.1f}{unit}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30, help="Look back this many days.")
    args = parser.parse_args()
    since = utc_now() - timedelta(days=args.days)
    with ENGINE.begin() as connection:
        events = [
            dict(row)
            for row in connection.execute(
                select(
                    agent_usage_events.c.request_kind,
                    agent_usage_events.c.success,
                    agent_usage_events.c.latency_ms,
                    agent_usage_events.c.completion_tokens,
                ).where(agent_usage_events.c.created_at >= since)
            ).mappings()
        ]
        ids = connection.execute(
            select(agent_conversations.c.id, agent_conversations.c.user_id).where(
                agent_conversations.c.updated_at >= since
            )
        ).all()
    conversations = [
        (get_conversation(conversation_id, user_id) or {}).get("messages") or []
        for conversation_id, user_id in ids
    ]

    calls = call_report(events)
    print(f"Model calls, last {args.days} days")
    print(f"  {'kind':24s} {'calls':>6s} {'fail':>5s} {'p50':>7s} {'p90':>7s} {'p99':>7s} {'max':>7s} {'out tok p50/p90':>16s}")
    for kind, row in sorted(calls.items()):
        tokens = f"{_fmt(row['p50_tokens'])}/{_fmt(row['p90_tokens'])}"
        print(
            f"  {kind:24s} {row['calls']:6d} {row['failures']:5d} {_fmt(row['p50_s'], 's'):>7s} "
            f"{_fmt(row['p90_s'], 's'):>7s} {_fmt(row['p99_s'], 's'):>7s} {_fmt(row['max_s'], 's'):>7s} {tokens:>16s}"
        )

    reply_p99 = (calls.get("chat_reply") or {}).get("p99_s")
    background_p99 = (calls.get("background_cognition") or {}).get("p99_s")
    print("\nTimeouts (p99 x 1.5, rounded to 5s)")
    print(
        f"  AGENT_REPLY_TIMEOUT_SECONDS          now {reply_timeout_seconds():.0f}s  "
        f"suggested {_fmt(suggested_timeout(reply_p99, low=10, high=60), 's')}"
    )
    print(
        f"  MEMORY_BACKGROUND_V2_TIMEOUT_SECONDS now {background_timeout():.0f}s  "
        f"suggested {_fmt(suggested_timeout(background_p99, low=60, high=300), 's')}"
    )

    pauses = pause_report(conversations)
    print(f"\nPauses between a user's messages ({pauses['pauses']} pauses)")
    for label, share in pauses["bands"].items():
        print(f"  {label:14s} {share * 100:5.1f}%")
    print(f"  median {_fmt(pauses['p50_min'], ' min')}, p90 {_fmt(pauses['p90_min'], ' min')}")
    print(
        f"  AGENT_SESSION_GAP_HOURS now {session_gap().total_seconds() / 3600:g}h: a good gap sits in "
        "the least common band between 1 hour and a day."
    )
    print(
        f"  AGENT_TIME_NOTE_GAP_MINUTES now {time_note_gap().total_seconds() / 60:g}: pauses longer "
        "than it get a time note; most pauses under 10 min should stay without one."
    )

    bubbles = bubble_report(conversations)
    print("\nBubbles per reply")
    print(f"  normal replies {bubbles['normal_replies']}, p90 {_fmt(bubbles['normal_p90_bubbles'])} (prompt asks for 1-3)")
    print(
        f"  story replies {bubbles['story_replies']}, p50 {_fmt(bubbles['story_p50_bubbles'])}, "
        f"p90 {_fmt(bubbles['story_p90_bubbles'])} (AGENT_MAX_REPLY_PARTS now {MAX_REPLY_PARTS})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
