"""The read of an uploaded chat: what code counts for the two sides, what it keeps of the written
half, and the API that makes, stores and returns it."""

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from agent.cognition.background.uploads.chat_read import build_chat_read, chat_counts, read_input, sample_lines, two_sides, validate_written
from api.main import app
from security.auth import CurrentUser, current_user
from storage import reset_db, save_conversation, save_context_source, save_user_profile
from storage.upload_digests import get_upload_digest, save_upload_digest

IST = ZoneInfo("Asia/Kolkata")
START = datetime(2026, 3, 1, 21, 0, tzinfo=IST)


def msg(role: str, text: str, minutes: float, speaker: str = "Riya Shah") -> dict:
    return {"role": role, **({"speaker": speaker} if role == "other" else {}), "content": text, "imported": True, "created_at": (START + timedelta(minutes=minutes)).isoformat()}


DAY = 24 * 60
CHAT = [
    msg("other", "hi, is this Aman?", 0),
    msg("user", "haha yes who is this", 2),
    msg("other", "Riya from the trek 😂", 3),
    msg("other", "you left your bottle", 20),              # she writes again before he answers
    msg("user", "oh no", 4 * 60),                          # 1 am, hours later: still a reply
    msg("user", "up at 2am again lol", DAY + 5 * 60),      # next day 02:00, he starts
    msg("other", "go to sleep? 😂😂", DAY + 5 * 60 + 1),
    msg("user", "trek on sunday?", 3 * DAY),               # two days of silence, he starts again
    msg("other", "yes!! chai after", 3 * DAY + 10),
]


class CountsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.kept, self.partner, self.others = two_sides(CHAT)
        self.counts = chat_counts(self.kept, IST)

    def test_sides_and_the_span(self) -> None:
        self.assertEqual((self.partner, self.others, len(self.kept)), ("Riya Shah", 1, 9))
        c = self.counts
        self.assertEqual((c["from"], c["to"], c["span_days"], c["days_talked"], c["messages"]), ("2026-03-01", "2026-03-04", 4, 4, 9))
        self.assertEqual((c["longest_streak_days"], c["longest_silence_days"], c["longest_silence_from"]), (4, 1, "2026-03-03"))  # the first evening runs past midnight, so four days in a row
        self.assertEqual(c["first_message"], {"who": "them", "date": "2026-03-01", "text": "hi, is this Aman?"})

    def test_who_starts_who_answers_and_who_laughs(self) -> None:
        me, them = self.counts["me"], self.counts["them"]
        self.assertEqual((me["messages"], them["messages"]), (4, 5))
        self.assertEqual((me["starts"], them["starts"]), (2, 1))             # she opened the chat, he opened the two later days
        self.assertEqual((me["last_words"], them["last_words"]), (1, 2))
        self.assertEqual((me["double_texts"], them["double_texts"]), (0, 1))
        self.assertEqual((me["reply_median_seconds"], them["reply_median_seconds"]), (6660, 60))  # his: 2 min and 3 h 40; hers: 1, 1 and 10 min
        self.assertEqual((me["laughs"], them["laughs"]), (2, 2))
        self.assertEqual((me["night_messages"], them["night_messages"]), (2, 1))
        self.assertEqual((me["questions"], them["questions"]), (1, 2))
        self.assertEqual(them["top_emoji"], ["😂"])
        self.assertEqual(self.counts["busiest_hour"], 21)

    def test_lines_without_a_time_or_words_are_left_out_and_a_group_is_seen(self) -> None:
        kept, partner, others = two_sides(CHAT + [{"role": "other", "speaker": "Dev", "content": "yo"}, msg("other", "  ", 5), msg("other", "hey all", 9 * DAY, speaker="Dev")])
        self.assertEqual((len(kept), partner, others), (10, "Riya Shah", 2))

    def test_the_sample_keeps_the_newest_half_and_spreads_the_rest(self) -> None:
        long = [msg("user" if i % 2 else "other", f"line {i}", i) for i in range(1000)]
        lines = sample_lines(long, IST, limit=100)
        numbers = [line["n"] for line in lines]
        self.assertEqual((len(numbers), numbers[-1], numbers[-50]), (100, 999, 950))
        self.assertEqual(numbers, sorted(numbers))
        self.assertLess(numbers[0], 20)
        self.assertEqual(lines[-1], {"n": 999, "who": "me", "day": "2026-03-02", "text": "line 999"})
        self.assertEqual(len(sample_lines(CHAT, IST)), 9)
        pack = json.loads(read_input("Aman", "Riya", self.counts, sample_lines(self.kept, IST)))
        self.assertNotIn("first_message", pack["counts"])  # the model is not handed a line to quote


class WrittenTest(unittest.TestCase):
    def test_only_what_the_shown_lines_support_is_kept(self) -> None:
        checked = validate_written({
            "headline": "Two night owls   who plan treks and never sleep",
            "you_two": "x" * 500,
            "roles": {"me": "the one awake at 2am", "them": 7},
            "running_jokes": [
                {"text": "the lost bottle", "lines": [3, 4]},
                {"text": "only one line", "lines": [3]},          # a joke needs two
                {"text": "made up", "lines": [77, 78]},            # lines never shown
                {"text": "The Lost Bottle", "lines": [3, 4]},      # said twice
            ],
            "keep_coming_back_to": [{"text": "the Sunday trek", "lines": [7, "8", True]}, {"text": "", "lines": [1]}],
            "friction": {"text": "He answers hours later.", "lines": [99]},
            "green_flag": "They always make a plan.",
            "roast": "One never sleeps, the other never stops laughing.",
        }, shown=set(range(9)))
        self.assertEqual(checked["headline"], "Two night owls who plan treks and never sleep")
        self.assertEqual(len(checked["you_two"]), 260)
        self.assertEqual(checked["roles"], {"me": "the one awake at 2am", "them": ""})
        self.assertEqual(checked["running_jokes"], [{"text": "the lost bottle", "lines": [3, 4]}])
        self.assertEqual(checked["keep_coming_back_to"], [{"text": "the Sunday trek", "lines": [7]}])
        self.assertIsNone(checked["friction"])
        self.assertEqual(validate_written("nonsense", set())["running_jokes"], [])


def long_chat(n: int = 30) -> list[dict]:
    return [msg("user" if i % 2 else "other", f"message number {i} haha", i * 7) for i in range(n)]


class BuildTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_read_needs_two_people_and_enough_from_each(self) -> None:
        writer = AsyncMock(return_value={"headline": "Two people, one bottle", "roast": "Both of you.", "running_jokes": [{"text": "numbers", "lines": [1, 2]}]})
        with patch("agent.providers.write_chat_read", writer):
            self.assertEqual(await build_chat_read(CHAT, me="Aman", zone=IST, conversation_id="c"), {"state": "too_short"})
            group = long_chat() + [msg("other", "hey", 999, speaker="Dev")]
            self.assertEqual(await build_chat_read(group, me="Aman", zone=IST, conversation_id="c"), {"state": "group_chat"})
            writer.assert_not_awaited()
            read = await build_chat_read(long_chat(), me="Aman", zone=IST, conversation_id="c")
        self.assertEqual((read["state"], read["me"], read["them"], read["counts"]["messages"]), ("ready", "Aman", "Riya", 30))
        self.assertEqual(read["written"]["running_jokes"], [{"text": "numbers", "lines": [1, 2]}])
        sent = json.loads(writer.await_args.args[0])
        self.assertEqual((sent["me"], sent["them"], len(sent["lines"])), ("Aman", "Riya", 30))

    async def test_the_numbers_stand_when_the_model_fails(self) -> None:
        with patch("agent.providers.write_chat_read", AsyncMock(side_effect=RuntimeError("down"))):
            read = await build_chat_read(long_chat(), me="Aman", zone=IST, conversation_id="c")
        self.assertEqual((read["state"], read["written"]), ("ready", None))
        with patch("agent.providers.write_chat_read", AsyncMock(return_value={})):
            self.assertIsNone((await build_chat_read(long_chat(), me="Aman", zone=IST, conversation_id="c"))["written"])


class _As:
    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

    def __enter__(self) -> TestClient:
        app.dependency_overrides[current_user] = lambda: CurrentUser(id=self.user_id, email=f"{self.user_id}@x.com", display_name=self.user_id)
        return TestClient(app)

    def __exit__(self, *_: object) -> None:
        app.dependency_overrides.pop(current_user, None)


class ApiTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        save_user_profile("ua", "male", "female", display_name="Aman Verma", city="Pune")
        save_conversation({"id": "chat-1", "status": "active", "messages": []}, "ua")
        self.source = save_context_source({"user_id": "ua", "conversation_id": "chat-1", "source_type": "whatsapp_chat", "title": "Riya", "content": "x", "metadata": {}})["id"]
        save_conversation({"id": "hidden-1", "status": "active", "import_source_id": self.source, "messages": long_chat()}, "ua")
        self.notes = save_context_source({"user_id": "ua", "conversation_id": "chat-1", "source_type": "notes", "title": "Notes", "content": "x", "metadata": {}})["id"]

    def test_make_store_return_and_keep_it_private(self) -> None:
        writer = AsyncMock(return_value={"headline": "Two people, thirty messages", "roast": "Both of you."})
        url = f"/api/me/context-sources/{self.source}/chat-read"
        with _As("ua") as client, patch("agent.providers.write_chat_read", writer):
            self.assertEqual(client.get(url).json(), {"state": "none"})
            made = client.post(url).json()
            self.assertEqual((made["state"], made["them"], made["written"]["headline"]), ("ready", "Riya", "Two people, thirty messages"))
            self.assertEqual(client.get(url).json()["counts"]["messages"], 30)
            client.post(url)  # stored: no second model call
            self.assertEqual(writer.await_count, 1)
            client.post(url + "?again=true")
            self.assertEqual(writer.await_count, 2)
            self.assertEqual(client.post(f"/api/me/context-sources/{self.notes}/chat-read").json(), {"state": "no_chat"})
        with _As("someone-else") as client:
            self.assertEqual(client.get(url).status_code, 404)
            self.assertEqual(client.post(url).status_code, 404)

    def test_the_read_survives_the_digest_being_written_and_goes_with_the_upload(self) -> None:
        url = f"/api/me/context-sources/{self.source}/chat-read"
        with _As("ua") as client, patch("agent.providers.write_chat_read", AsyncMock(return_value={"headline": "Kept"})):
            client.post(url)
            # The background reader stores its digest afterwards: the read stays in the same row.
            save_upload_digest(self.source, "ua", "hidden-1", "Riya Shah", {"summary": "a chat", "threads": []})
            self.assertEqual(client.get(url).json()["written"]["headline"], "Kept")
            self.assertEqual(get_upload_digest(self.source, "ua")["summary"], "a chat")
            self.assertEqual(client.delete(f"/api/me/context-sources/{self.source}").status_code, 200)
            self.assertEqual(client.get(url).status_code, 404)
        self.assertIsNone(get_upload_digest(self.source, "ua"))


if __name__ == "__main__":
    unittest.main()
