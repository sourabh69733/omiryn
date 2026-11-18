"""The read of an uploaded chat: what code counts for the two sides, what it keeps of the written
half, and the API that makes, stores and returns it."""

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from agent.cognition.background.uploads.chat_read import (
    NEWEST_LINES, READ_VERSION, SPREAD_LINES, build_chat_read, chat_counts, laugh_lines, make_stored_read, read_input, read_state_of, recurring_phrases,
    sample_lines, two_sides, validate_written,
)
from agent.evals.memory.planted_chat import ME as PLANTED_ME, PLANTED_JOKES, planted_export
from ingestion.upload_chat import whatsapp_upload_messages
from storage.upload_digests import CHAT_READ_KEY, set_upload_digest_part
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

    def test_the_sample_keeps_the_newest_lines_spreads_the_rest_and_marks_what_got_a_laugh(self) -> None:
        long = [msg("user" if i % 2 else "other", f"line {i}", i * 3) for i in range(1000)]
        long[100] = msg("other", "the bottle again", 300)
        long[101] = msg("user", "hahaha stop", 303)
        lines = sample_lines(long, IST)
        numbers = [line["n"] for line in lines]
        self.assertEqual(numbers, sorted(set(numbers)))
        self.assertEqual(numbers[-NEWEST_LINES:], list(range(1000 - NEWEST_LINES, 1000)))  # the newest in full
        self.assertLessEqual(len(numbers), NEWEST_LINES + SPREAD_LINES + 4)
        self.assertLess(numbers[0], 20)  # and something from the very start
        by_n = {line["n"]: line for line in lines}
        self.assertEqual((by_n[100]["laughed"], by_n[100]["who"], "laughed" in by_n[101]), (True, "them", False))  # the joke and the laugh after it are both shown
        self.assertEqual(len(sample_lines(CHAT, IST)), 9)
        pack = json.loads(read_input("Aman", "Riya", self.counts, sample_lines(self.kept, IST), [{"phrase": "bottle", "times": 4}]))
        self.assertNotIn("first_message", pack["counts"])  # the model is not handed a line to quote
        self.assertEqual(pack["phrases"], [{"phrase": "bottle", "times": 4}])


class JokesTest(unittest.TestCase):
    """What the two keep saying, found over the whole chat: a made-up chat with planted jokes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.messages, _, _ = two_sides(whatsapp_upload_messages(planted_export(), PLANTED_ME, IST))
        cls.phrases = recurring_phrases(cls.messages, IST)

    def test_a_laugh_line_is_one_the_other_person_laughed_at(self) -> None:
        chat = [
            msg("user", "tera paanch minute matlab ek ghanta", 0),
            msg("other", "hahaha 😂😂", 2),            # she laughs: line 0 landed
            msg("user", "haha", 3),                     # a laugh answering a laugh is not a joke
            msg("other", "lol", 4),
            msg("other", "ok serious now", 30),
            msg("user", "haha fine", 9 * 60),           # nine hours later: not a reaction
        ]
        self.assertEqual(laugh_lines(chat), [0])
        self.assertEqual(laugh_lines(chat, limit=0), [])

    def test_the_planted_jokes_are_found_and_come_first(self) -> None:
        top = [phrase["phrase"] for phrase in self.phrases[:6]]
        for joke in PLANTED_JOKES:
            self.assertTrue(any(joke in phrase or phrase in joke for phrase in top), (joke, top))
        first = self.phrases[0]
        self.assertGreaterEqual(first["got_laughs"], 10)
        self.assertEqual(first["times"], first["me"] + first["them"])
        self.assertTrue(all(0 <= n < len(self.messages) for n in first["lines"]))
        self.assertLessEqual(len(first["lines"]), 3)

    def test_ordinary_talk_and_one_off_lines_are_not_phrases(self) -> None:
        names = {phrase["phrase"] for phrase in self.phrases}
        self.assertFalse(names & {"hai", "ka", "ke", "rajmachi", "link", "phone"})  # filler, a word said once, what masking leaves
        self.assertTrue(all(phrase["times"] >= 4 and phrase["days"] >= 3 for phrase in self.phrases))
        # Pieces of one repeated sentence are told once, not as five overlapping phrases.
        self.assertEqual(sum(1 for name in names if "paanch" in name or "ghanta" in name), 1)
        self.assertEqual(recurring_phrases([], IST), [])


class WrittenTest(unittest.TestCase):
    def test_only_what_the_shown_lines_support_is_kept(self) -> None:
        checked = validate_written({
            "headline": "Two night owls   who plan treks and never sleep",
            "you_two": "They plan treks. " * 40,
            "roles": {"me": "the one awake at 2am", "them": 7},
            "running_jokes": [
                {"text": "the lost bottle", "about": "she still has it  ", "lines": [3, 4]},
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
        self.assertTrue(checked["you_two"].endswith("They plan treks."))  # cut at a whole sentence, not mid-word
        self.assertLessEqual(len(checked["you_two"]), 340)
        self.assertEqual(validate_written({"headline": "one " * 60}, set())["headline"][-1], "…")
        self.assertEqual(checked["roles"], {"me": "the one awake at 2am", "them": ""})
        self.assertEqual(checked["running_jokes"], [{"text": "the lost bottle", "about": "she still has it", "lines": [3, 4]}])
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
        self.assertEqual((sent["me"], sent["them"], len(sent["lines"]), read["version"]), ("Aman", "Riya", 30, READ_VERSION))
        self.assertIn("phrases", sent)

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

    def test_the_read_made_at_upload_is_waiting_and_costs_no_second_call(self) -> None:
        import asyncio

        url = f"/api/me/context-sources/{self.source}/chat-read"
        writer = AsyncMock(return_value={"headline": "Made at upload", "roast": "r"})
        with patch("agent.providers.write_chat_read", writer):
            made = asyncio.run(make_stored_read("ua", self.source))  # what the upload route runs in the background
            self.assertEqual((made["state"], made["them"]), ("ready", "Riya"))
            with _As("ua") as client:
                self.assertEqual(client.get(url).json()["written"]["headline"], "Made at upload")
                self.assertEqual(client.post(url).json()["written"]["headline"], "Made at upload")
        self.assertEqual(writer.await_count, 1)
        self.assertEqual(read_state_of(get_upload_digest(self.source, "ua")), "ready")
        self.assertEqual(asyncio.run(make_stored_read("ua", self.notes)), {"state": "no_chat"})

    def test_the_note_in_the_chat_is_told_when_the_read_is_ready(self) -> None:
        import asyncio

        with _As("ua") as client:
            self.assertIsNone(client.get(f"/api/me/context-sources/{self.source}/reading").json()["read"])
            with patch("agent.providers.write_chat_read", AsyncMock(return_value={"headline": "h"})):
                asyncio.run(make_stored_read("ua", self.source))
            body = client.get(f"/api/me/context-sources/{self.source}/reading").json()
            self.assertEqual((body["read"], body["state"]), ("ready", "none"))

    def test_while_one_is_being_made_nobody_starts_another(self) -> None:
        url = f"/api/me/context-sources/{self.source}/chat-read"
        now = datetime.now(timezone.utc)
        writer = AsyncMock(return_value={"headline": "late"})
        with _As("ua") as client, patch("agent.providers.write_chat_read", writer):
            set_upload_digest_part(self.source, "ua", "hidden-1", None, CHAT_READ_KEY, {"state": "making", "started_at": now.isoformat()})
            self.assertEqual(client.get(url).json(), {"state": "making"})
            self.assertEqual(client.post(url).json(), {"state": "making"})
            self.assertEqual(client.post(url + "?again=true").json(), {"state": "making"})
            writer.assert_not_awaited()
            # A read that has been "being made" for ten minutes was lost in a restart: made again.
            set_upload_digest_part(self.source, "ua", "hidden-1", None, CHAT_READ_KEY, {"state": "making", "started_at": (now - timedelta(minutes=10)).isoformat()})
            self.assertEqual(client.get(url).json(), {"state": "none"})
            self.assertEqual(client.post(url).json()["state"], "ready")
        self.assertEqual(writer.await_count, 1)

    def test_a_chat_with_no_read_keeps_the_reason_and_is_not_tried_again(self) -> None:
        save_conversation({"id": "hidden-2", "status": "active", "import_source_id": self.notes, "messages": CHAT}, "ua")  # nine messages: too short
        url = f"/api/me/context-sources/{self.notes}/chat-read"
        with _As("ua") as client, patch("agent.cognition.background.uploads.chat_read.build_chat_read", AsyncMock(return_value={"state": "too_short"})) as build:
            self.assertEqual(client.post(url).json(), {"state": "too_short"})
            self.assertEqual(client.get(url).json(), {"state": "too_short"})
            self.assertEqual(client.post(url).json(), {"state": "too_short"})
        self.assertEqual(build.await_count, 1)
        self.assertEqual(read_state_of(get_upload_digest(self.notes, "ua")), "too_short")
        self.assertIsNone(read_state_of(None))
        self.assertIsNone(read_state_of({"chat_read": {"state": "ready", "version": READ_VERSION - 1}}))

    def test_a_failed_read_at_upload_never_fails_the_upload(self) -> None:
        import asyncio

        from api.routes.context import _make_read

        with patch("agent.cognition.background.uploads.chat_read.make_stored_read", AsyncMock(side_effect=RuntimeError("down"))):
            asyncio.run(_make_read("ua", self.source))  # logged, not raised

    def test_a_read_made_by_an_older_version_is_made_again(self) -> None:
        url = f"/api/me/context-sources/{self.source}/chat-read"
        set_upload_digest_part(self.source, "ua", "hidden-1", "Riya", CHAT_READ_KEY, {"state": "ready", "version": READ_VERSION - 1, "written": {"headline": "old"}})
        writer = AsyncMock(return_value={"headline": "new", "roast": "r"})
        with _As("ua") as client, patch("agent.providers.write_chat_read", writer):
            self.assertEqual(client.get(url).json(), {"state": "none"})
            self.assertEqual(client.post(url).json()["written"]["headline"], "new")
            self.assertEqual(client.get(url).json()["version"], READ_VERSION)

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
