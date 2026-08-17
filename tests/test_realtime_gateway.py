"""Verifies authentication, room authorization, and generic message delivery."""

from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient

from api.main import app, current_user
from realtime import RealtimeTicketError, issue_realtime_ticket, verify_realtime_ticket
from security.auth import CurrentUser
from storage import reset_db


class RealtimeGatewayTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["AUTH_REQUIRED"] = "false"
        os.environ["AGENT_PROVIDER"] = "mock"
        os.environ["REALTIME_TICKET_SECRET"] = "test-realtime-secret"
        app.dependency_overrides.clear()

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="realtime-user", email="realtime@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        reset_db()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        os.environ.pop("REALTIME_TICKET_SECRET", None)

    def test_ticket_is_short_lived_signed_and_rejects_tampering(self) -> None:
        issued = issue_realtime_ticket("user-a", ttl_seconds=30, now=100)

        self.assertEqual(verify_realtime_ticket(issued["ticket"], now=129), "user-a")
        with self.assertRaises(RealtimeTicketError):
            verify_realtime_ticket(issued["ticket"], now=131)
        with self.assertRaises(RealtimeTicketError):
            verify_realtime_ticket(f"{issued['ticket']}x", now=110)

    def test_authenticated_socket_can_subscribe_only_to_owned_conversation(self) -> None:
        conversation = self.client.post("/api/agent/conversations", json={}).json()
        ticket_response = self.client.post("/api/realtime/ticket")
        self.assertEqual(ticket_response.status_code, 201)
        ticket = ticket_response.json()["ticket"]

        with self.client.websocket_connect(f"/api/realtime?ticket={ticket}") as socket:
            connected = socket.receive_json()
            self.assertEqual(connected["type"], "realtime.connected")

            socket.send_json(
                {
                    "type": "subscribe",
                    "scope": "conversation",
                    "scope_id": conversation["id"],
                }
            )
            subscribed = socket.receive_json()
            self.assertEqual(subscribed["type"], "realtime.subscribed")

            socket.send_json(
                {
                    "type": "subscribe",
                    "scope": "conversation",
                    "scope_id": "not-owned",
                }
            )
            denied = socket.receive_json()
            self.assertEqual(denied["type"], "realtime.error")

    def test_agent_turn_publishes_ordered_message_events(self) -> None:
        conversation = self.client.post("/api/agent/conversations", json={}).json()
        ticket = self.client.post("/api/realtime/ticket").json()["ticket"]

        with self.client.websocket_connect(f"/api/realtime?ticket={ticket}") as socket:
            socket.receive_json()
            socket.send_json(
                {
                    "type": "subscribe",
                    "scope": "conversation",
                    "scope_id": conversation["id"],
                }
            )
            socket.receive_json()

            response = self.client.post(
                f"/api/agent/conversations/{conversation['id']}/messages",
                json={"message": "hello"},
            )
            self.assertEqual(response.status_code, 200)

            user_event = socket.receive_json()
            assistant_event = socket.receive_json()
            self.assertEqual(user_event["type"], "message.created")
            self.assertEqual(user_event["payload"]["message"]["role"], "user")
            self.assertEqual(assistant_event["payload"]["message"]["role"], "assistant")
            self.assertEqual(
                [user_event["sequence"], assistant_event["sequence"]],
                [1, 2],
            )

    def test_reconnect_can_recover_messages_missed_while_disconnected(self) -> None:
        conversation = self.client.post("/api/agent/conversations", json={}).json()
        first_ticket = self.client.post("/api/realtime/ticket").json()["ticket"]
        with self.client.websocket_connect(f"/api/realtime?ticket={first_ticket}") as socket:
            socket.receive_json()
            socket.send_json(
                {
                    "type": "subscribe",
                    "scope": "conversation",
                    "scope_id": conversation["id"],
                }
            )
            socket.receive_json()

        response = self.client.post(
            f"/api/agent/conversations/{conversation['id']}/messages",
            json={"message": "sent while the socket is disconnected"},
        )
        self.assertEqual(response.status_code, 200)

        second_ticket = self.client.post("/api/realtime/ticket").json()["ticket"]
        with self.client.websocket_connect(f"/api/realtime?ticket={second_ticket}") as socket:
            socket.receive_json()
            socket.send_json(
                {
                    "type": "subscribe",
                    "scope": "conversation",
                    "scope_id": conversation["id"],
                }
            )
            socket.receive_json()

            recovered = self.client.get(
                f"/api/agent/conversations/{conversation['id']}/messages",
                params={"after_sequence": 0},
            )
            self.assertEqual(recovered.status_code, 200)
            body = recovered.json()
            messages = body["messages"]
            self.assertEqual(len(messages), 2)
            self.assertEqual(body["latest_sequence"], 2)
            self.assertEqual([item["message_index"] for item in messages], [1, 2])
            self.assertEqual(
                messages[0]["message"]["content"],
                "sent while the socket is disconnected",
            )


if __name__ == "__main__":
    unittest.main()
