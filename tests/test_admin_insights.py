"""The fast admin pages: counts, days, attention items, and no chat or memory text."""

import json
import os
import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.shared.clock import utc_now
from api.main import app
from storage import list_audit_events, reset_db, save_agent_usage_event, save_conversation
from storage.database import ENGINE
from storage.schema import agent_jobs, agent_memories, app_events, memory_batch_failures, user_profiles

ANNA = "anna"
BEN = "ben"
SECRET = "my sister lives in Pune"


def _reply(user_id: str, *, success: bool = True, days_ago: float = 0, cost: float = 0.001, latency: int = 900) -> None:
    save_agent_usage_event(
        {
            "user_id": user_id,
            "conversation_id": f"{user_id}-chat",
            "request_kind": "chat_reply",
            "provider": "deepinfra",
            "model": "reply-model",
            "success": success,
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "latency_ms": latency,
            "estimated_cost_usd": cost,
            "error": None if success else "provider timed out",
            "created_at": utc_now() - timedelta(days=days_ago),
        }
    )


def _seed() -> None:
    now = utc_now()
    save_conversation({"id": "anna-chat", "status": "active", "messages": [{"role": "user", "content": SECRET}]}, ANNA)
    save_conversation({"id": "ben-chat", "status": "active", "messages": []}, BEN)
    with ENGINE.begin() as connection:
        connection.execute(
            user_profiles.insert(),
            [
                {"user_id": ANNA, "display_name": "Anna", "city": "Pune", "created_at": now - timedelta(days=20), "updated_at": now},
                {"user_id": BEN, "display_name": "Ben", "city": None, "created_at": now - timedelta(days=1), "updated_at": now},
            ],
        )
        connection.execute(
            app_events.insert(),
            [
                {"id": "e1", "user_id": ANNA, "event_name": "app_opened", "metadata_json": {}, "created_at": now - timedelta(days=12)},
                {"id": "e2", "user_id": ANNA, "event_name": "quota.chat_message", "metadata_json": {}, "created_at": now},
            ],
        )
        connection.execute(
            agent_memories.insert().values(
                id="m1", user_id=ANNA, kind="person", purposes_json=[], key="sister", value_json={"text": SECRET},
                statement=SECRET, allowed_uses_json=[], status="active", sensitivity="normal", confidence=0.9,
                importance=0.5, schema_version=3, created_at=now, updated_at=now,
            )
        )
        connection.execute(
            agent_jobs.insert().values(
                id="j1", kind="memory_flush", dedupe_key="j1", user_id=ANNA, status="failed", run_after=now,
                attempts=5, last_error="model refused", created_at=now, updated_at=now,
            )
        )
        connection.execute(
            memory_batch_failures.insert().values(
                batch_key="b1", conversation_id="anna-chat", user_id=ANNA, attempts=2, last_error="bad json", updated_at=now
            )
        )
    _reply(ANNA, cost=0.002)
    _reply(ANNA, success=False)
    _reply(ANNA, days_ago=10)
    _reply(BEN, latency=3000)


class AdminInsightsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"AUTH_REQUIRED": "false", "AGENT_PROVIDER": "mock"})
        self.env.start()
        reset_db()
        _seed()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.env.stop()

    def get(self, path: str) -> dict:
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(SECRET, response.text)
        return response.json()

    def test_dashboard_counts_people_replies_and_trouble(self) -> None:
        data = self.get("/api/admin/dashboard")
        kpis = data["kpis"]
        self.assertEqual(kpis["users_total"], 2)
        self.assertEqual(kpis["active_today"], 2)
        self.assertEqual(kpis["active_prev_7d"], 1)
        self.assertEqual(kpis["returning_7d"], 1)
        self.assertEqual(kpis["new_users_7d"], 1)
        self.assertEqual(kpis["replies_today"], 2)
        self.assertEqual(kpis["failed_today"], 1)
        self.assertEqual(kpis["messages_7d"], 1)
        self.assertAlmostEqual(kpis["cost_today"], 0.004)

        self.assertEqual(len(data["daily"]), 14)
        today = data["daily"][-1]
        self.assertEqual((today["active_users"], today["replies"], today["failed_replies"]), (2, 2, 1))
        self.assertEqual(data["omi"]["reply_model"], "reply-model")
        self.assertEqual(data["omi"]["latency_samples"], 2)
        self.assertEqual(data["health"]["memories_active"], 1)

        titles = [item["title"] for item in data["attention"]]
        self.assertEqual(titles[:3], ["Failed replies today", "Background jobs failed", "Memory batches failing"])
        self.assertEqual(data["attention"][0]["detail"], "provider timed out")

    def test_people_list_sorts_by_last_activity(self) -> None:
        people = self.get("/api/admin/people")["people"]
        self.assertEqual({person["user_id"] for person in people}, {ANNA, BEN})
        anna = next(person for person in people if person["user_id"] == ANNA)
        self.assertEqual((anna["replies"], anna["replies_7d"], anna["failed_replies"]), (2, 1, 1))
        self.assertEqual((anna["memories"], anna["chats"], anna["place"]), (1, 1, "Pune"))

    def test_person_shows_counts_not_content_and_is_audited(self) -> None:
        person = self.get(f"/api/admin/people/{ANNA}")
        self.assertEqual(person["profile"]["display_name"], "Anna")
        self.assertEqual(person["memory"]["active"], 1)
        self.assertEqual(person["memory"]["by_kind"], [{"kind": "person", "active": 1, "total": 1}])
        self.assertEqual(person["memory"]["batch_failures"], 1)
        self.assertEqual(person["chats"][0]["replies"], 2)
        self.assertEqual(len(person["usage"]["daily"]), 30)
        self.assertNotIn("messages", json.dumps(person["chats"]))
        actions = [(event["action"], event["target_user_id"]) for event in list_audit_events()]
        self.assertIn(("admin.view_user", ANNA), actions)

        self.assertEqual(self.client.get("/api/admin/people/nobody").status_code, 404)

    def test_costs_group_by_day_kind_and_model(self) -> None:
        data = self.get("/api/admin/costs?days=30")
        self.assertEqual(data["totals"]["calls"], 4)
        self.assertEqual(data["totals"]["failed"], 1)
        self.assertEqual(data["by_kind"][0]["request_kind"], "chat_reply")
        self.assertEqual(data["by_model"][0]["model"], "reply-model")
        self.assertEqual(data["reply_latency"]["samples"], 3)
        self.assertEqual([row["error"] for row in data["recent_failures"]], ["provider timed out"])
        self.assertEqual(sum(day["calls"] for day in data["daily"]), 4)

    def test_system_lists_failed_jobs_and_memory_batches(self) -> None:
        data = self.get("/api/admin/system")
        self.assertEqual(data["jobs"]["by_kind"][0]["failed"], 1)
        self.assertEqual(data["jobs"]["problems"][0]["last_error"], "model refused")
        self.assertEqual(data["memory"]["batch_failures"][0]["last_error"], "bad json")
        self.assertIn("prompt_version", data["config"])


if __name__ == "__main__":
    unittest.main()
