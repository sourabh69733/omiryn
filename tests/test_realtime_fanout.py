"""An event published on one instance reaches a socket open on another."""

import os
import unittest
from unittest.mock import patch

from realtime.contracts import conversation_event
from realtime.fanout import RealtimeFanout
from realtime.hub import InMemoryRealtimeHub
from storage import append_realtime_event, realtime_events_after, reset_db

USER_ID = "fanout-user"
CHAT = "fanout-chat"


class _Socket:
    def __init__(self) -> None:
        self.received: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.received.append(payload)


async def _instance(name: str) -> tuple[InMemoryRealtimeHub, RealtimeFanout, _Socket]:
    hub = InMemoryRealtimeHub(name)
    fanout = RealtimeFanout(hub)
    hub.attach_fanout(fanout)
    socket = _Socket()
    connection = await hub.register(socket, USER_ID)
    await hub.subscribe(connection, "conversation", CHAT)
    await fanout.drain()  # the first read only marks where this instance starts
    return hub, fanout, socket


class FanoutTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        reset_db()

    async def test_an_event_from_another_instance_reaches_the_local_socket(self) -> None:
        hub_a, fanout_a, socket_a = await _instance("a")
        hub_b, fanout_b, socket_b = await _instance("b")

        await hub_a.publish(conversation_event("message.created", CHAT, sequence=3, payload={"message_index": 3}))

        self.assertEqual([event["sequence"] for event in socket_a.received], [3])
        self.assertEqual(socket_b.received, [])
        self.assertEqual(await fanout_b.drain(), 1)
        self.assertEqual([(event["type"], event["sequence"]) for event in socket_b.received], [("message.created", 3)])
        # Reading again delivers nothing twice, and A never gets its own event back.
        self.assertEqual(await fanout_b.drain(), 0)
        self.assertEqual(await fanout_a.drain(), 0)
        self.assertEqual(len(socket_a.received), 1)

    async def test_events_before_an_instance_started_are_not_replayed(self) -> None:
        append_realtime_event("old-instance", conversation_event("message.created", CHAT, sequence=1).as_dict())
        hub_b, fanout_b, socket_b = await _instance("b")
        self.assertEqual(await fanout_b.drain(), 0)
        self.assertEqual(socket_b.received, [])

    async def test_switched_off_means_no_rows(self) -> None:
        hub_a, fanout_a, socket_a = await _instance("a")
        with patch.dict(os.environ, {"REALTIME_FANOUT": "off"}):
            await hub_a.publish(conversation_event("message.created", CHAT, sequence=1))
        self.assertEqual(realtime_events_after(0, exclude_instance="none"), [])
        self.assertEqual(len(socket_a.received), 1)

    async def test_a_bad_row_is_skipped(self) -> None:
        hub_b, fanout_b, socket_b = await _instance("b")
        append_realtime_event("a", {"type": "message.created"})
        append_realtime_event("a", conversation_event("agent.typing", CHAT).as_dict())
        self.assertEqual(await fanout_b.drain(), 1)
        self.assertEqual(socket_b.received[0]["type"], "agent.typing")


if __name__ == "__main__":
    unittest.main()
