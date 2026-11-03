"""Covers Omi answering without words: one emoji on the user's message, or nothing at all."""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from agent.context_engine.policy.replies import is_one_emoji, strip_quiet_markers
from agent.context_engine.prompt_engine.versions.v4_1 import V4_1_GOAL
from agent.context_engine.prompt_engine.versions.v4_2 import V4_2_GOAL
from agent.providers import _provider_messages
from agent.runtime.steps import assistant_messages, finish_reply
from security.auth import CurrentUser
from api.chat_service import _unanswered_indexes
from api.main import app, current_user
from storage import get_conversation, reset_db

USER_ID = "wordless-user"


class MarkersTest(unittest.TestCase):
    def test_a_reaction_alone_makes_no_bubble(self) -> None:
        finished = finish_reply("<react:👍>", "hmm")
        self.assertEqual((finished.reaction, finished.no_reply, finished.parts), ("👍", False, []))
        self.assertEqual(assistant_messages(finished, {}), [])

    def test_saying_nothing_makes_no_bubble(self) -> None:
        finished = finish_reply("<no_reply>", "hmm")
        self.assertEqual((finished.reaction, finished.no_reply, finished.parts), (None, True, []))

    def test_words_are_never_lost_to_a_marker(self) -> None:
        with_reaction = finish_reply("<react:😂> that was good", "joke")
        self.assertEqual((with_reaction.reaction, with_reaction.parts), ("😂", ["that was good"]))
        with_silence = finish_reply("<no_reply> theek hai", "ok")
        self.assertEqual((with_silence.no_reply, with_silence.parts), (False, ["theek hai"]))

    def test_a_bad_reaction_is_never_shown(self) -> None:
        for marker in ("<react:nice>", "<react:>", "<react:👍 👍>", "<react:" + "👍" * 20 + ">"):
            with self.subTest(marker=marker):
                self.assertEqual(strip_quiet_markers(marker), ("", None, True))

    def test_emoji_with_joiners_counts_as_one(self) -> None:
        self.assertEqual(strip_quiet_markers("<react:👍🏽>")[1], "👍🏽")
        self.assertEqual(strip_quiet_markers("<react:❤️‍🔥>")[1], "❤️‍🔥")

    def test_keycaps_and_flags_count_as_one_emoji(self) -> None:
        for emoji in ("1️⃣", "🇮🇳", "❤️", "©️"):
            with self.subTest(emoji=emoji):
                self.assertTrue(is_one_emoji(emoji))
        for text in ("nice", "हाँ", "12", "—", "👍 👍", ""):
            with self.subTest(text=text):
                self.assertFalse(is_one_emoji(text))

    def test_plain_text_is_untouched(self) -> None:
        finished = finish_reply("kya hua?", "hmm")
        self.assertEqual((finished.reaction, finished.no_reply, finished.parts), (None, False, ["kya hua?"]))


class AnsweredTest(unittest.TestCase):
    def test_a_wordless_answer_closes_the_message(self) -> None:
        for mark in ({"reaction": "👍"}, {"no_reply": True}):
            with self.subTest(mark=mark):
                messages = [{"role": "user", "content": "hmm", **mark}, {"role": "user", "content": "suno"}]
                self.assertEqual(_unanswered_indexes(messages), [1])
                self.assertEqual(_unanswered_indexes(messages[:1]), [])

    def test_a_plain_user_message_stays_unanswered(self) -> None:
        self.assertEqual(_unanswered_indexes([{"role": "user", "content": "hmm"}]), [0])


class HistoryTest(unittest.TestCase):
    def test_the_model_sees_how_it_answered(self) -> None:
        sent = _provider_messages(
            [
                {"role": "user", "content": "hmm", "reaction": "👍"},
                {"role": "user", "content": "go silent", "no_reply": True},
                {"role": "user", "content": "suno"},
            ]
        )
        self.assertEqual(
            [(message["role"], message["content"]) for message in sent],
            [("user", "hmm"), ("assistant", "<react:👍>"), ("user", "go silent"), ("assistant", "<no_reply>"), ("user", "suno")],
        )


class OverTheApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {"AUTH_REQUIRED": "false", "AGENT_PROVIDER": "mock", "DATA_POINT_EXTRACTOR": "rules",
             "AGENT_PIPELINE_VERSION": "v1", "AGENT_ROLLOUT": "off", "AGENT_REQUEST_CHECK": "false"},
        )
        self.env.start()
        app.dependency_overrides.clear()

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id=USER_ID, email="wordless@example.com", display_name="Wordless User")

        app.dependency_overrides[current_user] = signed_in_user
        reset_db()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.env.stop()

    def _chat(self, replies: list[str], texts: list[str]) -> tuple[list[dict], AsyncMock]:
        generate = AsyncMock(side_effect=replies)

        async def scenario() -> str:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                conversation_id = (await client.post("/api/agent/conversations")).json()["id"]
                for text in texts:
                    response = await client.post(f"/api/agent/conversations/{conversation_id}/messages", json={"message": text})
                    self.assertEqual(response.status_code, 200)
            return conversation_id

        with patch("agent.runtime.orchestrator.generate_agent_reply", generate):
            conversation_id = asyncio.run(scenario())
        return get_conversation(conversation_id, USER_ID)["messages"][1:], generate

    def test_a_reaction_lands_on_the_message_with_no_bubble(self) -> None:
        messages, _ = self._chat(["<react:👍>"], ["hmm"])
        self.assertEqual(len(messages), 1)
        self.assertEqual((messages[0]["reaction"], messages[0]["delivery_status"]), ("👍", "read"))

    def test_saying_nothing_is_saved_as_an_answer(self) -> None:
        messages, _ = self._chat(["<no_reply>"], ["go silent now"])
        self.assertEqual(len(messages), 1)
        self.assertTrue(messages[0]["no_reply"])
        self.assertEqual(messages[0]["delivery_status"], "read")

    def test_the_next_message_is_read_alone_and_the_model_sees_the_reaction(self) -> None:
        messages, generate = self._chat(["<react:👍>", "haan bolo"], ["hmm", "suno"])
        self.assertEqual([m["content"] for m in messages], ["hmm", "suno", "haan bolo"])
        sent = generate.await_args_list[1].args[0]
        self.assertEqual(sent[-1]["content"].split()[-1], "suno")
        self.assertIn("<react:👍>", [m["content"] for m in _provider_messages(sent)])


    def _react(self, calls: list[tuple[str, int, str | None]]) -> tuple[list[dict], list[int]]:
        statuses: list[int] = []

        async def scenario() -> str:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                conversation_id = (await client.post("/api/agent/conversations")).json()["id"]
                await client.post(f"/api/agent/conversations/{conversation_id}/messages", json={"message": "hmm"})
                for method, index, emoji in calls:
                    url = f"/api/agent/conversations/{conversation_id}/messages/{index}/reaction"
                    response = await client.request(method, url, **({"json": {"emoji": emoji}} if emoji else {}))
                    statuses.append(response.status_code)
            return conversation_id

        with patch("agent.runtime.orchestrator.generate_agent_reply", AsyncMock(return_value="haan bolo")):
            conversation_id = asyncio.run(scenario())
        return get_conversation(conversation_id, USER_ID)["messages"], statuses

    def test_the_user_reacts_to_omi_and_takes_it_back(self) -> None:
        messages, statuses = self._react([("PUT", 2, "❤️")])
        self.assertEqual(statuses, [200])
        self.assertEqual(messages[2]["user_reaction"], "❤️")
        self.assertEqual(len(messages), 3)  # no reply is started

        messages, statuses = self._react([("PUT", 2, "❤️"), ("PUT", 2, "😂"), ("DELETE", 2, None)])
        self.assertEqual(statuses, [200, 200, 200])
        self.assertNotIn("user_reaction", messages[2])

    def test_a_reaction_needs_one_of_omis_messages_and_one_emoji(self) -> None:
        _, statuses = self._react([("PUT", 1, "❤️"), ("PUT", 99, "❤️"), ("PUT", -1, "❤️"), ("PUT", 2, "nice")])
        self.assertEqual(statuses, [404, 404, 404, 422])


class SeesTheUsersReactionTest(unittest.TestCase):
    def test_the_model_is_told_what_they_reacted_to(self) -> None:
        sent = _provider_messages(
            [
                {"role": "assistant", "content": "ek joke", "user_reaction": "😂"},
                {"role": "user", "content": "aur suna"},
            ]
        )
        self.assertEqual(
            [m["content"] for m in sent], ["ek joke", "[They reacted 😂 to your message above.]", "aur suna"]
        )


class VersionTest(unittest.TestCase):
    def test_only_the_line_about_little_changes_and_v4_1_is_kept(self) -> None:
        self.assertIn("one word or one emoji", V4_1_GOAL)
        self.assertNotIn("<no_reply>", V4_1_GOAL)
        self.assertIn("<no_reply>", V4_2_GOAL)
        self.assertIn("Say something only this conversation could produce.", V4_2_GOAL)


if __name__ == "__main__":
    unittest.main()
