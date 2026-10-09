"""Retention deletes expired debug rows on its own; the audit log records who touched private data."""

import os
import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from agent.shared.clock import utc_now
from api.main import app, current_user
from security.auth import CurrentUser
from storage import (
    get_conversation,
    list_audit_events,
    purge_expired_records,
    record_audit_event,
    reset_db,
    save_agent_trace,
    save_conversation,
)
from storage.database import ENGINE
from storage.schema import agent_conversations, agent_traces, audit_events

USER_ID = "retention-user"


def _count(table) -> int:
    with ENGINE.begin() as connection:
        return connection.execute(select(func.count()).select_from(table)).scalar_one()


def _age(table, days: float) -> None:
    with ENGINE.begin() as connection:
        connection.execute(update(table).values(created_at=utc_now() - timedelta(days=days)))


class RetentionTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": "chat", "status": "active", "messages": []}, USER_ID)
        save_agent_trace({"user_id": USER_ID, "conversation_id": "chat", "turn_index": 0, "status": "ok", "summary": {}})

    def test_recent_debug_rows_stay_and_expired_ones_go(self) -> None:
        self.assertEqual(purge_expired_records()["traces"], 0)
        _age(agent_traces, 31)

        self.assertEqual(purge_expired_records()["traces"], 1)
        self.assertEqual(_count(agent_traces), 0)
        # Chats are never removed by retention, however old.
        with ENGINE.begin() as connection:
            connection.execute(update(agent_conversations).values(updated_at=utc_now() - timedelta(days=400)))
        purge_expired_records()
        self.assertIsNotNone(get_conversation("chat", USER_ID))

    def test_a_stale_temporary_chat_of_any_user_is_deleted(self) -> None:
        save_conversation({"id": "temp", "status": "active", "temporary": True, "messages": []}, "someone-else")
        with ENGINE.begin() as connection:
            connection.execute(update(agent_conversations).values(updated_at=utc_now() - timedelta(hours=25)))

        self.assertEqual(purge_expired_records()["temporary_chats"], 1)
        self.assertIsNone(get_conversation("temp", "someone-else"))

    def test_audit_rows_keep_a_year_then_go(self) -> None:
        record_audit_event("chat.delete", actor_id=USER_ID, actor_role="user", target_user_id=USER_ID)
        _age(audit_events, 364)
        self.assertEqual(purge_expired_records()["audit_events"], 0)
        _age(audit_events, 366)
        self.assertEqual(purge_expired_records()["audit_events"], 1)


class AuditLogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"AUTH_REQUIRED": "false", "AGENT_PROVIDER": "mock"})
        self.env.start()

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id=USER_ID, email="a@example.com", display_name="A")

        app.dependency_overrides[current_user] = signed_in_user
        reset_db()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.env.stop()

    def test_deleting_a_chat_is_recorded_without_content(self) -> None:
        chat = self.client.post("/api/agent/conversations").json()["id"]
        self.client.delete(f"/api/agent/conversations/{chat}")

        [event] = list_audit_events(target_user_id=USER_ID)
        self.assertEqual((event["action"], event["actor_role"], event["target_id"]), ("chat.delete", "user", chat))
        self.assertEqual(event["detail"], {"temporary": False})

    def test_free_text_never_lands_in_an_audit_row(self) -> None:
        record_audit_event(
            "omi.clear", actor_id=USER_ID, actor_role="user",
            detail={"memories": 3, "note": "I live in Pune and love dark humor"},
        )
        self.assertEqual(list_audit_events()[0]["detail"], {"memories": 3})

    def test_an_admin_viewing_a_user_is_recorded(self) -> None:
        self.client.get(f"/api/admin/users/{USER_ID}")

        actions = [(event["action"], event["actor_role"], event["target_user_id"]) for event in list_audit_events()]
        self.assertIn(("admin.view_user", "admin", USER_ID), actions)


if __name__ == "__main__":
    unittest.main()
