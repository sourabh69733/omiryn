"""The talk-style card: code counts how a user writes to Omi; two users' counts become plain pair
lines for the match judge, and hard gaps (no common language, no common hours) for the pick.
Nothing is judged, and too few messages gives no lines."""

import unittest
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import storage
from agent.matching.style import MIN_MESSAGES, pair_style_lines, rebuild_user_style, style_counts, style_gaps

ZONE = ZoneInfo("Asia/Kolkata")
USER_ID = "style-user"


def _chat(texts: list[str], *, start: datetime, step: timedelta = timedelta(seconds=40), reply_lag: timedelta = timedelta(seconds=20), opened_by: str = "user") -> dict:
    """One session: Omi answers each message; `opened_by` decides who writes first."""
    messages = []
    at = start
    if opened_by == "assistant":
        messages.append({"role": "assistant", "content": "Hey, kya haal?", "created_at": at.isoformat(), "proactive": True})
        at += reply_lag
    for text in texts:
        messages.append({"role": "user", "content": text, "created_at": at.isoformat()})
        at += reply_lag
        messages.append({"role": "assistant", "content": "ok", "created_at": at.isoformat()})
        at += step
    return {"id": f"chat-{start.timestamp()}", "status": "active", "messages": messages}


def _night_hinglish(n: int) -> list[dict]:
    base = datetime(2026, 11, 1, 22, 0, tzinfo=ZONE)  # 10 pm local, every night
    return [_chat(["haan yaar bas kaam tha", "kya bolu haha 😂"] * 2, start=base + timedelta(days=i)) for i in range(n)]


def _day_english(n: int) -> list[dict]:
    base = datetime(2026, 11, 1, 11, 0, tzinfo=ZONE)  # 11 am local
    long = "I spent the whole morning reorganising my notes for the exam and then went for a long walk around the lake near the office."
    return [_chat([long, "Not really, I prefer to plan things a week ahead so nobody has to scramble on the day, and I keep a list for it."] * 2, start=base + timedelta(days=i), step=timedelta(minutes=10), opened_by="assistant") for i in range(n)]


class StyleCountsTest(unittest.TestCase):
    def test_counts_language_hours_length_and_pace(self) -> None:
        counts = style_counts(_night_hinglish(10), ZONE)
        self.assertEqual(counts["message_count"], 40)
        self.assertEqual(counts["days"], 10)
        self.assertGreaterEqual(counts["hinglish_share"], 0.9)
        self.assertEqual(set(counts["hours"]), {"22"})
        self.assertAlmostEqual(counts["laugh_share"], 0.5, places=2)
        self.assertEqual(counts["reply_lag_median_seconds"], 40)
        self.assertEqual(counts["sessions"], 10)
        self.assertEqual(counts["opened_by_user_share"], 1.0)
        self.assertLessEqual(counts["chars_median"], 40)

        other = style_counts(_day_english(10), ZONE)
        self.assertEqual(other["english_share"], 1.0)
        self.assertEqual(other["opened_by_user_share"], 0.0)
        self.assertEqual(other["reply_lag_median_seconds"], 600)
        self.assertGreaterEqual(other["long_share"], 0.5)

    def test_temporary_chats_and_undated_messages_are_skipped(self) -> None:
        chats = _night_hinglish(2)
        chats[0]["temporary"] = True
        chats[1]["messages"].append({"role": "user", "content": "no date"})
        self.assertEqual(style_counts(chats, ZONE)["message_count"], 4)


class PairLinesTest(unittest.TestCase):
    def test_lines_name_the_differences_and_the_overlap(self) -> None:
        a, b = style_counts(_night_hinglish(10), ZONE), style_counts(_day_english(10), ZONE)
        lines = pair_style_lines(a, b, "Priya", "Rohan")
        self.assertIn("Priya writes mostly Hinglish, Rohan mostly English", lines)
        self.assertIn("Priya usually writes in the night, Rohan in the morning; their hours do not overlap", lines)
        self.assertIn("Priya writes short, Rohan writes long", lines)
        self.assertIn("Priya laughs in text a lot, Rohan rarely", lines)
        self.assertIn("Priya comes back within a minute, Rohan after a while", lines)
        self.assertIn("Priya usually starts the conversation, Rohan waits to be nudged", lines)
        self.assertEqual(style_gaps(a, b), ("language", "hours"))

        same = pair_style_lines(a, a, "Priya", "Meera")
        self.assertIn("both write mostly Hinglish", same)
        self.assertIn("both usually write in the night", same)
        self.assertIn("both laugh in text often", same)
        self.assertEqual(style_gaps(a, a), ())

    def test_too_few_messages_gives_nothing(self) -> None:
        a = style_counts(_night_hinglish(2), ZONE)
        self.assertLess(a["message_count"], MIN_MESSAGES)
        b = style_counts(_day_english(10), ZONE)
        self.assertEqual(pair_style_lines(a, b, "A", "B"), [])
        self.assertEqual(style_gaps(a, b), ())


class StoredStyleTest(unittest.TestCase):
    def setUp(self) -> None:
        storage.reset_db()
        storage.set_user_timezone(USER_ID, "Asia/Kolkata")

    def test_rebuild_stores_the_counts_and_deletion_removes_them(self) -> None:
        for chat in _night_hinglish(8):
            storage.save_conversation(chat, USER_ID)
        counts = rebuild_user_style(USER_ID)
        self.assertEqual(counts["message_count"], 32)
        self.assertEqual(storage.get_user_style(USER_ID), counts)
        self.assertIsNotNone(storage.user_style_built_at(USER_ID))
        storage.delete_user_private_data(USER_ID)
        self.assertIsNone(storage.get_user_style(USER_ID))


if __name__ == "__main__":
    unittest.main()
