"""The tuning report measures timeouts, pauses and bubble counts from plain rows."""

import unittest

from agent.observability.tuning import (
    bubble_report,
    call_report,
    pause_report,
    percentile,
    suggested_timeout,
)


class TuningMetricsTest(unittest.TestCase):
    def test_percentile_is_nearest_rank(self) -> None:
        self.assertEqual(percentile([1, 2, 3, 4, 10], 0.5), 3)
        self.assertEqual(percentile([1, 2, 3, 4, 10], 0.99), 10)
        self.assertIsNone(percentile([], 0.5))

    def test_call_report_splits_kinds_and_counts_failures(self) -> None:
        events = [
            {"request_kind": "chat_reply", "success": True, "latency_ms": 3000, "completion_tokens": 20},
            {"request_kind": "chat_reply", "success": True, "latency_ms": 5000, "completion_tokens": 40},
            {"request_kind": "chat_reply", "success": False, "latency_ms": 45000},
            {"request_kind": "background_cognition", "success": True, "latency_ms": 40000, "completion_tokens": 700},
        ]
        report = call_report(events)
        self.assertEqual((report["chat_reply"]["calls"], report["chat_reply"]["failures"]), (3, 1))
        self.assertEqual(report["chat_reply"]["p99_s"], 5.0)
        self.assertEqual(report["background_cognition"]["p50_tokens"], 700)

    def test_suggested_timeout_adds_headroom_within_bounds(self) -> None:
        self.assertEqual(suggested_timeout(12.0, low=10, high=60), 20.0)
        self.assertEqual(suggested_timeout(100.0, low=10, high=60), 60.0)
        self.assertIsNone(suggested_timeout(None, low=10, high=60))

    def test_pause_report_bands_user_pauses_only(self) -> None:
        chat = [
            {"role": "user", "created_at": "2026-09-26T10:00:00+00:00"},
            {"role": "assistant", "created_at": "2026-09-26T10:00:05+00:00"},
            {"role": "user", "created_at": "2026-09-26T10:05:00+00:00"},
            {"role": "user", "created_at": "2026-09-26T12:05:00+00:00"},
            {"role": "user", "created_at": "2026-09-28T12:05:00+00:00"},
        ]
        report = pause_report([chat])
        self.assertEqual(report["pauses"], 3)
        self.assertAlmostEqual(report["bands"]["under 10 min"], 1 / 3)
        self.assertAlmostEqual(report["bands"]["1-6 hours"], 1 / 3)
        self.assertAlmostEqual(report["bands"]["over a day"], 1 / 3)

    def test_bubble_report_separates_story_replies(self) -> None:
        at, later = "2026-09-26T10:00:00+00:00", "2026-09-26T10:01:00+00:00"
        chat = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "created_at": at},
            {"role": "user", "content": "story?"},
            *({"role": "assistant", "story": True, "created_at": later} for _ in range(5)),
            {"role": "assistant", "proactive": True, "created_at": "2026-09-26T11:00:00+00:00"},
        ]
        report = bubble_report([chat])
        self.assertEqual((report["normal_replies"], report["story_replies"]), (1, 1))
        self.assertEqual(report["story_p90_bubbles"], 5)


if __name__ == "__main__":
    unittest.main()
