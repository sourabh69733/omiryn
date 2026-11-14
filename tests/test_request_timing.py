"""API calls are timed per route template and saved as per-minute summaries, never per request."""

import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import app
from api.request_timing import RequestTimer, request_timer
from storage import histogram_percentile, latency_bucket, merge_histograms, reset_db
from storage.database import ENGINE
from storage.request_stats import REQUEST_LATENCY_BOUNDS_MS
from storage.schema import api_request_stats

MINUTE = datetime(2026, 11, 14, 10, 30, tzinfo=timezone.utc)


class RequestTimerTest(unittest.TestCase):
    def test_calls_in_one_minute_and_route_become_one_row(self) -> None:
        timer = RequestTimer()
        timer.record("GET", "/api/x/{id}", 200, 30, at=MINUTE)
        timer.record("GET", "/api/x/{id}", 500, 900, at=MINUTE + timedelta(seconds=40))
        timer.record("GET", "/api/x/{id}", 404, 10, at=MINUTE + timedelta(seconds=50))
        timer.record("GET", "/api/x/{id}", 200, 20, at=MINUTE + timedelta(minutes=1))

        [row] = timer.take(finished_before=MINUTE + timedelta(minutes=1, seconds=5))
        self.assertEqual((row["count"], row["server_errors"], row["client_errors"]), (3, 1, 1))
        self.assertEqual((row["total_ms"], row["max_ms"]), (940, 900))
        self.assertEqual(sum(row["histogram_json"]), 3)
        # The minute still running stays in memory until it ends.
        self.assertEqual(len(timer.take()), 1)
        self.assertEqual(timer.take(), [])

    def test_histogram_buckets_and_percentiles(self) -> None:
        self.assertEqual(latency_bucket(25), 0)
        self.assertEqual(latency_bucket(26), 1)
        self.assertEqual(latency_bucket(10**6), len(REQUEST_LATENCY_BOUNDS_MS))
        merged = merge_histograms([[8, 1, 0, 0, 0, 1], [1]])
        self.assertEqual(merged[:6], [9, 1, 0, 0, 0, 1])
        self.assertEqual(histogram_percentile(merged, 0.5), 25)
        self.assertEqual(histogram_percentile(merged, 0.99), 800)
        self.assertIsNone(histogram_percentile([0, 0], 0.5))


class RequestTimingMiddlewareTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        request_timer.take()

    def test_the_route_template_is_kept_not_the_real_path(self) -> None:
        client = TestClient(app)
        client.get("/api/admin/people/someone-private")
        client.get("/api/does-not-exist")
        request_timer.flush(everything=True)

        with ENGINE.connect() as connection:
            rows = connection.execute(select(api_request_stats.c.route, api_request_stats.c.count)).all()
        routes = {route for route, _ in rows}
        self.assertIn("/api/admin/people/{user_id}", routes)
        self.assertIn("unmatched", routes)
        self.assertNotIn("someone-private", " ".join(routes))


if __name__ == "__main__":
    unittest.main()
