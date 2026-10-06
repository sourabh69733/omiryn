"""The background model sees how often and when the user said what backs each memory."""

import unittest

from agent.cognition.background.service import memory_history
from agent.shared.timeline import user_zone


def _said(at: str, quote: str) -> dict:
    return {"observed_at": at, "exact_quote": quote}


class MemoryHistoryTest(unittest.TestCase):
    def test_counts_days_dates_and_latest_words(self) -> None:
        memory = {
            "evidence": [
                _said("2026-09-25T15:00:00+00:00", "Love Bangalore weather"),
                _said("2026-09-02T15:00:00+00:00", "I live in Bangalore"),
                _said("2026-09-02T16:00:00+00:00", "Bangalore traffic is killing me"),
            ]
        }

        history = memory_history(memory, user_zone("Asia/Kolkata"))

        self.assertEqual(history["said_times"], 3)
        self.assertEqual(history["said_on_days"], 2)
        self.assertEqual(history["first_said"], "Wed 2 Sep 2026")
        self.assertEqual(history["last_said"], "Fri 25 Sep 2026")
        self.assertEqual(history["latest_words"], ["Bangalore traffic is killing me", "Love Bangalore weather"])

    def test_a_memory_without_proof_has_an_empty_history(self) -> None:
        self.assertEqual(memory_history({}, user_zone(None))["said_times"], 0)


if __name__ == "__main__":
    unittest.main()
