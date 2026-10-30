#!/usr/bin/env python3
"""Check that a realtime event published on one server instance reaches a socket on another.

  .venv/bin/python scripts/check_realtime_fanout.py                 against DATABASE_URL from .env
  DATABASE_URL=postgresql://... .venv/bin/python scripts/check_realtime_fanout.py

Two in-process hubs share the database. Instance B opens a socket and starts its reader with a
long poll (60 s); instance A publishes one event. On Postgres the event must arrive within about
a second: that proves LISTEN/NOTIFY woke the reader, since the poll alone would take a minute.
On SQLite there is no NOTIFY, so the script sets a one-second poll and only checks the log.
The table is created if missing; the one test row is deleted at the end. Prints no secrets.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from realtime.contracts import conversation_event  # noqa: E402
from realtime.fanout import RealtimeFanout, _postgres_dsn  # noqa: E402
from realtime.hub import InMemoryRealtimeHub  # noqa: E402
from storage import init_db  # noqa: E402
from storage.database import ENGINE  # noqa: E402
from storage.schema import realtime_events  # noqa: E402

CHAT = "fanout-check"


class _Socket:
    def __init__(self) -> None:
        self.received: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.received.append(payload)


async def main() -> int:
    init_db()
    postgres = _postgres_dsn() is not None
    print(f"database: {'postgres (LISTEN/NOTIFY expected)' if postgres else 'sqlite (poll only)'}")

    hub_a = InMemoryRealtimeHub("check-a")
    hub_a.attach_fanout(RealtimeFanout(hub_a))
    hub_b = InMemoryRealtimeHub("check-b")
    fanout_b = RealtimeFanout(hub_b, poll_seconds=60.0 if postgres else 1.0)
    hub_b.attach_fanout(fanout_b)
    socket = _Socket()
    connection = await hub_b.register(socket, "fanout-check-user")
    await hub_b.subscribe(connection, "conversation", CHAT)
    fanout_b.start()
    await asyncio.sleep(1.5)  # the reader marks its start and, on Postgres, LISTEN connects

    started = time.perf_counter()
    event = conversation_event("agent.typing", CHAT, payload={"check": True})
    await hub_a.publish(event)
    for _ in range(100):
        if socket.received:
            break
        await asyncio.sleep(0.05)
    elapsed_ms = (time.perf_counter() - started) * 1000
    await fanout_b.stop()
    await hub_b.reset()
    with ENGINE.begin() as db:
        db.execute(realtime_events.delete().where(realtime_events.c.instance_id.in_(["check-a", "check-b"])))

    if not socket.received:
        print("FAIL: the event never reached instance B (check REALTIME_FANOUT and the database)")
        return 1
    print(f"ok: event reached instance B after {elapsed_ms:.0f} ms")
    if postgres and elapsed_ms > 3000:
        print("WARN: slower than NOTIFY should be; the reader may be running on the poll only")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
