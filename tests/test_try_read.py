"""The read before sign-in: made in memory, nothing stored, limited, and kept after sign-in."""

from __future__ import annotations

import asyncio
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select

from agent.cognition.background.uploads.chat_read import READ_VERSION, make_stored_read, read_status
from agent.cognition.background.uploads.sealed_read import SEAL_FOR_SECONDS, keyed_mark, open_sealed_read, same_chat, seal_read
from api.main import app
from api.routes.try_read import TRY_READ_EVENT
from security.auth import CurrentUser, current_user
from storage import list_conversations, list_user_context_sources, reset_db, save_user_profile
from storage.database import ENGINE
from storage.schema import public_events

IST = ZoneInfo("Asia/Kolkata")
START = datetime(2026, 3, 1, 21, 0, tzinfo=IST)


def export(n: int = 30, third: str | None = None) -> str:
    lines = []
    for i in range(n):
        at = START + timedelta(minutes=17 * i)
        who = "Aman Verma" if i % 2 else "Riya Shah"
        lines.append(f"{at:%d/%m/%Y}, {at:%-I:%M} {at:%p}".lower() + f" - {who}: message number {i} haha")
    if third:
        lines.append(f"02/03/2026, 9:00 am - {third}: hello all")
    return "\n".join(lines)


WRITTEN = {"headline": "Two people, thirty messages", "roast": "Both of you count out loud."}
HEADERS = {"X-Timezone": "Asia/Kolkata", "X-Forwarded-For": "8.8.4.4"}


def events() -> list[dict]:
    with ENGINE.connect() as connection:
        return [dict(row) for row in connection.execute(select(public_events).where(public_events.c.event_name == TRY_READ_EVENT)).mappings()]


class SealTest(unittest.TestCase):
    READ = {"state": "ready", "version": READ_VERSION, "me": "Aman", "them": "Riya", "counts": {"messages": 30, "from": "2026-03-01", "to": "2026-03-02", "days_talked": 2, "me": {"messages": 15, "words": 60.0}, "them": {"messages": 15, "words": 60}}, "written": {"headline": "ह"}}

    def test_a_seal_opens_to_the_same_read_and_only_ours_does(self) -> None:
        seal = seal_read(self.READ, now=1000)
        self.assertEqual(open_sealed_read(seal, now=1001), self.READ)
        body, signature = seal.split(".")
        self.assertIsNone(open_sealed_read(f"{body}x.{signature}", now=1001))
        self.assertIsNone(open_sealed_read(f"{body}.{signature[:-2]}aa", now=1001))
        with patch.dict(os.environ, {"CHAT_READ_SEAL_SECRET": "another server"}):
            self.assertIsNone(open_sealed_read(seal, now=1001))
        for junk in (None, "", "abc", "a.b.c", "x" * 50_000):
            self.assertIsNone(open_sealed_read(junk))

    def test_a_seal_ends_and_an_older_kind_of_read_is_not_kept(self) -> None:
        seal = seal_read(self.READ, now=1000)
        self.assertIsNone(open_sealed_read(seal, now=1000 + SEAL_FOR_SECONDS + 1))
        self.assertIsNone(open_sealed_read(seal_read({**self.READ, "version": READ_VERSION - 1})))
        self.assertIsNone(open_sealed_read(seal_read({"state": "too_short"})))

    def test_the_same_chat_is_the_same_size_days_and_split(self) -> None:
        counts = self.READ["counts"]
        self.assertTrue(same_chat(self.READ, counts))
        self.assertFalse(same_chat(self.READ, {**counts, "messages": 31}))
        self.assertFalse(same_chat(self.READ, {**counts, "to": "2026-03-03"}))
        self.assertFalse(same_chat(self.READ, {**counts, "me": {"messages": 14, "words": 60}}))

    def test_a_mark_does_not_show_the_address(self) -> None:
        mark = keyed_mark("8.8.4.4", "try-read-address")
        self.assertNotIn("8.8", mark)
        self.assertEqual(mark, keyed_mark("8.8.4.4", "try-read-address"))
        self.assertNotEqual(mark, keyed_mark("8.8.8.8", "try-read-address"))


class TryReadTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        app.dependency_overrides.pop(current_user, None)
        self.env = patch.dict(os.environ, {"AUTH_REQUIRED": "true"})
        self.env.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.env.stop()

    def ask(self, content: str | None = None, sender: str = "Aman Verma", headers: dict | None = None):
        return self.client.post("/api/public/chat-read", json={"content": content or export(), "user_sender": sender}, headers=headers or HEADERS)

    def test_a_read_with_no_account_and_nothing_of_the_chat_kept(self) -> None:
        writer = AsyncMock(return_value=WRITTEN)
        with patch("agent.providers.write_chat_read", writer):
            response = self.ask()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual((body["state"], body["me"], body["them"], body["counts"]["messages"], body["written"]["headline"]), ("ready", "Aman", "Riya", 30, WRITTEN["headline"]))
        self.assertEqual(writer.await_args.kwargs["conversation_id"], "")
        self.assertEqual(open_sealed_read(body["kept"]), {key: value for key, value in body.items() if key != "kept"})
        [row] = events()
        self.assertEqual(row["metadata_json"], {"messages": 30})
        stored = " ".join(str(value) for value in row.values())
        for private in ("8.8.4.4", "Aman", "Riya", "message number"):
            self.assertNotIn(private, stored)

    def test_a_chat_with_no_read_costs_nothing_and_is_not_counted(self) -> None:
        writer = AsyncMock(return_value=WRITTEN)
        with patch("agent.providers.write_chat_read", writer):
            self.assertEqual(self.ask(export(third="Dev Rao")).json(), {"state": "group_chat"})
            self.assertEqual(self.ask(export(n=8)).json(), {"state": "too_short"})
            self.assertEqual(self.ask(sender="Nobody Here").status_code, 400)
            self.assertEqual(self.ask("just some notes about my week, nothing like a chat export at all").status_code, 400)
        writer.assert_not_awaited()
        self.assertEqual(events(), [])

    def test_each_address_and_everyone_together_have_a_daily_share(self) -> None:
        writer = AsyncMock(return_value=WRITTEN)
        with patch("agent.providers.write_chat_read", writer), patch.dict(os.environ, {"PUBLIC_CHAT_READ_PER_ADDRESS_DAILY": "2", "PUBLIC_CHAT_READ_DAILY_LIMIT": "3"}):
            self.assertEqual([self.ask().status_code for _ in range(3)], [200, 200, 429])
            self.assertEqual(self.ask().json()["detail"]["code"], "sign_in_to_read")
            other = {**HEADERS, "X-Forwarded-For": "1.1.1.1"}
            self.assertEqual(self.ask(headers=other).status_code, 200)
            self.assertEqual(self.ask(headers=other).status_code, 429)  # everyone together: three a day
        self.assertEqual(writer.await_count, 3)
        with patch.dict(os.environ, {"PUBLIC_CHAT_READ_DAILY_LIMIT": "0"}):
            self.assertEqual(self.ask().status_code, 404)

    def test_a_browser_cannot_use_up_the_share_by_writing_the_count_itself(self) -> None:
        response = self.client.post("/api/public/events", json={"event_name": TRY_READ_EVENT, "path": "/try"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.post("/api/public/events", json={"event_name": "try_opened", "path": "/try"}).status_code, 201)


class KeepTest(unittest.TestCase):
    """After sign-in the same chat is shared the usual way, with the seal."""

    USER = "keeper"

    def setUp(self) -> None:
        reset_db()
        self.env = patch.dict(os.environ, {"AUTH_REQUIRED": "false", "AGENT_PIPELINE_VERSION": "v3", "DATA_POINT_EXTRACTOR": "rules", "MEMORY_EMBEDDING_MODEL": "off"})
        self.env.start()
        app.dependency_overrides.pop(current_user, None)
        self.client = TestClient(app)
        save_user_profile(self.USER, "male", "female", display_name="Aman V", city="Pune")

    def tearDown(self) -> None:
        app.dependency_overrides.pop(current_user, None)
        self.env.stop()

    def tried(self, writer: AsyncMock, content: str | None = None) -> dict:
        with patch("agent.providers.write_chat_read", writer):
            return self.client.post("/api/public/chat-read", json={"content": content or export(), "user_sender": "Aman Verma"}, headers=HEADERS).json()

    def share(self, kept: str | None, content: str | None = None) -> str:
        app.dependency_overrides[current_user] = lambda: CurrentUser(id=self.USER, email="k@example.com", display_name="Aman V")
        conversation_id = self.client.post("/api/agent/conversations", headers=HEADERS).json()["id"]
        with patch("agent.cognition.background.uploads.hidden_chat.request_flush_now"), patch("agent.matching.notes.add_upload_to_notes", AsyncMock()):
            response = self.client.post(
                f"/api/agent/conversations/{conversation_id}/whatsapp-import",
                json={"title": "Riya", "content": content or export(), "user_sender": "Aman Verma", "style_kind": "user_style", "kept_read": kept},
                headers=HEADERS,
            )
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def test_nothing_is_stored_until_sign_in(self) -> None:
        self.tried(AsyncMock(return_value=WRITTEN))
        self.assertEqual(list_conversations(self.USER), [])
        self.assertEqual(list_user_context_sources(self.USER), [])

    def test_the_read_they_saw_is_the_read_they_keep(self) -> None:
        writer = AsyncMock(return_value=WRITTEN)
        tried = self.tried(writer)
        with patch("agent.providers.write_chat_read", writer):
            source_id = self.share(tried["kept"])
        stored = read_status(source_id, self.USER)
        self.assertEqual(stored, {key: value for key, value in tried.items() if key != "kept"})
        self.assertEqual(writer.await_count, 1)  # written once, before sign-in

    def test_a_seal_of_another_chat_or_a_broken_one_is_ignored(self) -> None:
        tried = self.tried(AsyncMock(return_value=WRITTEN), export(n=40))
        writer = AsyncMock(return_value={"headline": "Made after sign-in", "roast": "r"})
        with patch("agent.providers.write_chat_read", writer):
            other = self.share(tried["kept"])                       # sealed from a longer chat
            broken = self.share("not-a-seal.at-all")
            none = self.share(None)
        for source_id in (other, broken, none):
            self.assertEqual(read_status(source_id, self.USER)["written"]["headline"], "Made after sign-in")
        self.assertEqual(writer.await_count, 3)

    def test_keeping_is_also_refused_for_a_chat_that_cannot_have_a_read(self) -> None:
        tried = self.tried(AsyncMock(return_value=WRITTEN))
        source_id = self.share(None, export(n=8))
        made = asyncio.run(make_stored_read(self.USER, source_id, kept=open_sealed_read(tried["kept"])))
        self.assertEqual(made, {"state": "too_short"})


if __name__ == "__main__":
    unittest.main()
