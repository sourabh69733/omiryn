"""Admin Experience and Growth pages: sign-in health, time per page, speed, errors, returns and funnels."""

import os
import unittest
from datetime import timedelta
from itertools import count
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.shared.clock import utc_now
from api.main import app
from storage import reset_db, save_agent_usage_event, save_request_stats
from storage.database import ENGINE
from storage.request_stats import REQUEST_LATENCY_BOUNDS_MS
from storage.schema import app_events, match_pairs, public_events, user_profiles

ANNA = "anna"
BEN = "ben"
_ids = count()


def _app_event(user_id: str, name: str, page: str, metadata: dict, days_ago: float = 0) -> dict:
    return {
        "id": f"e{next(_ids)}",
        "user_id": user_id,
        "session_id": f"s-{user_id}",
        "event_name": name,
        "page": page,
        "metadata_json": metadata,
        "created_at": utc_now() - timedelta(days=days_ago),
    }


def _public(name: str, session: str, metadata: dict | None = None) -> dict:
    return {"id": f"p{next(_ids)}", "session_id": session, "event_name": name, "path": "/", "metadata_json": metadata or {}, "created_at": utc_now()}


def _histogram(bucket: int, calls: int) -> list[int]:
    histogram = [0] * (len(REQUEST_LATENCY_BOUNDS_MS) + 1)
    histogram[bucket] = calls
    return histogram


def _seed() -> None:
    now = utc_now()
    with ENGINE.begin() as connection:
        connection.execute(
            public_events.insert(),
            [
                _public("sign_in_screen_viewed", "s1"),
                _public("sign_in_screen_viewed", "s2"),
                _public("sign_in_screen_viewed", "s3"),
                _public("sign_in_started", "s1"),
                _public("sign_in_started", "s2"),
                _public("sign_in_started", "s3"),
                _public("sign_in_failed", "s3", {"reason": "access_denied"}),
            ],
        )
        connection.execute(
            app_events.insert(),
            [
                _app_event(ANNA, "sign_in_succeeded", "sign_in", {"duration_ms": 9000}),
                _app_event(BEN, "sign_in_succeeded", "sign_in", {"duration_ms": 15000}),
                _app_event(ANNA, "page_left", "chat", {"active_ms": 60000, "visible_ms": 90000, "reason": "navigate"}),
                _app_event(ANNA, "page_left", "vibe", {"active_ms": 2000, "visible_ms": 3000, "reason": "navigate"}),
                _app_event(BEN, "page_left", "chat", {"active_ms": 20000, "visible_ms": 25000, "reason": "hidden"}),
                _app_event(ANNA, "page_speed", "chat", {"metric": "LCP", "value": 1800, "rating": "good"}),
                _app_event(BEN, "page_speed", "chat", {"metric": "LCP", "value": 4200, "rating": "poor"}),
                _app_event(ANNA, "client_error", "chat", {"message_code": "boom", "source": "index.js:12", "release": "abc123"}),
                _app_event(BEN, "client_error", "chat", {"message_code": "boom", "source": "index.js:12", "release": "abc123"}),
                _app_event(BEN, "rage_click", "vibe", {"target": "button.chip"}),
                # Anna joined two weeks ago and came back the next day and in her second week.
                _app_event(ANNA, "app_opened", "chat", {}, days_ago=14),
                _app_event(ANNA, "app_opened", "chat", {}, days_ago=13),
                _app_event(ANNA, "app_opened", "chat", {}, days_ago=5),
                _app_event(BEN, "quota.chat_message", "chat", {}, days_ago=0),
            ],
        )
        connection.execute(user_profiles.insert(), [{"user_id": BEN, "display_name": "Ben", "city": None, "created_at": now, "updated_at": now}])
        connection.execute(
            match_pairs.insert(),
            [
                {"id": f"pair{i}", "pool_id": "pool", "user_a": "x", "user_b": "y", "status": status, "check_json": {}, "plan_json": {}, "created_at": now, "updated_at": now}
                for i, status in enumerate(["proposed", "asked", "introduced", "met", "still_talking", "declined"])
            ],
        )
    save_agent_usage_event(
        {"user_id": BEN, "request_kind": "chat_reply", "provider": "p", "model": "m", "success": True, "created_at": utc_now()}
    )
    minute = now.replace(second=0, microsecond=0)
    save_request_stats(
        [
            {"bucket_start": minute, "release": "r1", "method": "GET", "route": "/api/fast", "count": 10, "server_errors": 0, "client_errors": 0, "total_ms": 200.0, "max_ms": 30.0, "histogram_json": _histogram(0, 10)},
            {"bucket_start": minute, "release": "r1", "method": "POST", "route": "/api/slow", "count": 4, "server_errors": 1, "client_errors": 0, "total_ms": 12000.0, "max_ms": 5000.0, "histogram_json": _histogram(8, 4)},
        ]
    )


class AdminExperienceTest(unittest.TestCase):
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
        return response.json()

    def test_sign_in_health(self) -> None:
        sign_in = self.get("/api/admin/experience?days=7")["sign_in"]
        self.assertEqual((sign_in["screen_sessions"], sign_in["started"], sign_in["succeeded"], sign_in["failed"]), (3, 3, 2, 1))
        self.assertAlmostEqual(sign_in["success_rate"], 0.6667, places=3)
        self.assertEqual(sign_in["failures"], [{"reason": "access_denied", "count": 1}])
        self.assertEqual(sign_in["duration_p50_ms"], 9000)
        self.assertEqual(sum(day["started"] for day in sign_in["daily"]), 3)

    def test_time_by_page_speed_errors_and_rage_clicks(self) -> None:
        data = self.get("/api/admin/experience?days=7")
        chat, vibe = data["pages"]
        self.assertEqual((chat["page"], chat["visits"], chat["users"], chat["active_ms"]), ("chat", 2, 2, 80000))
        self.assertAlmostEqual(chat["share"], 80000 / 82000, places=3)
        self.assertEqual((vibe["page"], vibe["quick_exit_rate"]), ("vibe", 1.0))

        lcp = data["speed"]["overall"]["metrics"]["LCP"]
        self.assertEqual((lcp["samples"], lcp["good_share"]), (2, 0.5))

        [error] = data["errors"]
        self.assertEqual((error["message_code"], error["source"], error["count"], error["users"], error["releases"]), ("boom", "index.js:12", 2, 2, ["abc123"]))
        self.assertEqual(data["rage_clicks"], [{"page": "vibe", "target": "button.chip", "count": 1, "users": 1}])

    def test_api_timing_ranks_slow_routes_first(self) -> None:
        api = self.get("/api/admin/experience?days=7")["api"]
        self.assertEqual((api["calls"], api["server_errors"]), (14, 1))
        slow, fast = api["routes"]
        self.assertEqual((slow["route"], slow["p95_ms"], slow["avg_ms"], slow["server_errors"]), ("/api/slow", 6400, 3000, 1))
        self.assertEqual((fast["route"], fast["p50_ms"]), ("/api/fast", 25))

    def test_growth_returns_cohorts_and_funnels(self) -> None:
        data = self.get("/api/admin/growth?weeks=4")
        returns = {row["key"]: row for row in data["returns"]}
        self.assertEqual((returns["next_day"]["eligible"], returns["next_day"]["returned"]), (1, 1))
        self.assertEqual((returns["week_two"]["eligible"], returns["week_two"]["returned"]), (1, 1))
        self.assertEqual(returns["month"]["eligible"], 0)

        self.assertEqual(len(data["cohorts"]), 4)
        self.assertEqual(sum(cohort["users"] for cohort in data["cohorts"]), 2)

        steps = {step["label"]: step["count"] for step in data["getting_started"]["steps"]}
        self.assertEqual(steps["Saw the sign-in screen"], 3)
        self.assertEqual(steps["Signed in (new users)"], 2)
        self.assertEqual(steps["Finished setup"], 1)
        self.assertEqual(steps["Got a reply from Omi"], 1)

        matching = {step["key"]: step["count"] for step in data["matching"]["steps"]}
        self.assertEqual((matching["proposed"], matching["asked"], matching["introduced"], matching["met"], matching["still_talking"]), (6, 5, 3, 2, 1))


if __name__ == "__main__":
    unittest.main()
