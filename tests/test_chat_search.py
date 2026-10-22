"""The reply model's search over past chats: real lines, forgiving spelling, rare words first."""

import os
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from agent.memory_engine.search import SEARCH_TOOL, search_chats, search_note
from agent.providers.gateway.clients import TOOL_CALL_MARKER, parse_tool_call
from agent.runtime.orchestrator import _answer_with_search
from storage import reset_db, save_conversation, set_user_timezone

USER_ID = "chat-search-user"
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


def _message(role: str, text: str, day: int, speaker: str | None = None) -> dict:
    return {"role": role, "content": text, "created_at": f"2026-10-{day:02d}T10:00:00+00:00", **({"speaker": speaker} if speaker else {})}


class ChatSearchTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        set_user_timezone(USER_ID, "Asia/Kolkata")
        save_conversation(
            {
                "id": "upload",
                "status": "active",
                "import_source_id": "src",
                "messages": [
                    _message("other", "guess what, my shaadi is fixed, engagement in december", 2, "Farheen Parvez"),
                    _message("user", "omg congrats!! kaun hai ladka", 2),
                    _message("other", "work is killing me, 8 review cycles", 15, "Farheen Parvez"),
                    _message("user", "same here, what about you", 15),
                    # Everyday talk: what makes "what" and "about" common words.
                    *[_message("user" if n % 2 else "other", f"what about {word} today, tell me about it", 16, None if n % 2 else "Farheen Parvez") for n, word in enumerate(["lunch", "work", "gym", "movie", "rain", "office", "sleep", "dinner", "tea", "plans", "weekend", "music", "news", "cricket", "class", "bus", "traffic", "rent", "phone", "laptop"] * 3)],
                ],
            },
            USER_ID,
        )
        save_conversation(
            {
                "id": "omi",
                "status": "active",
                "messages": [
                    _message("user", "I went for a trek to Sinhagad today", 20),
                    _message("assistant", "Wow, how was the view?", 20),
                ],
            },
            USER_ID,
        )
        save_conversation(
            {"id": "temp", "status": "active", "temporary": True, "messages": [_message("user", "secret engagement plan", 21)]},
            USER_ID,
        )

    def test_spelling_and_endings_still_match(self) -> None:
        hits = search_chats(USER_ID, "shadi engaged", now=NOW)
        self.assertEqual(hits[0].chat, "WhatsApp chat with Farheen Parvez (uploaded)")
        self.assertIn('Farheen Parvez: guess what, my shaadi is fixed, engagement in december', hits[0].lines)
        self.assertIn("User: omg congrats!! kaun hai ladka", hits[0].lines)

    def test_common_words_alone_find_nothing(self) -> None:
        self.assertEqual(search_chats(USER_ID, "what about", now=NOW), [])

    def test_temporary_chats_are_never_searched(self) -> None:
        self.assertTrue(all("secret" not in line for hit in search_chats(USER_ID, "engagement plan", now=NOW) for line in hit.lines))

    def test_person_and_days_narrow_the_search(self) -> None:
        self.assertEqual(search_chats(USER_ID, "trek", person="Farheen", now=NOW), [])
        recent = search_chats(USER_ID, "", days=5, now=NOW)
        self.assertEqual([hit.chat for hit in recent], ["chat with you"])
        self.assertIn("User: I went for a trek to Sinhagad today", recent[0].lines)
        self.assertIn("You (Omi): Wow, how was the view?", recent[0].lines)

    def test_the_note_tells_the_model_to_answer_from_lines_or_say_so(self) -> None:
        self.assertIn("found nothing", search_note("wedding", "Farheen", None, []))
        note = search_note("trek", None, None, search_chats(USER_ID, "trek", now=NOW))
        self.assertIn("your own earlier words, not facts", note)
        self.assertIn("Sinhagad", note)


class SearchInReplyTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": "upload", "status": "active", "import_source_id": "src", "messages": [_message("other", "my shaadi is fixed", 2, "Farheen")]}, USER_ID)

    async def test_a_search_call_is_run_and_the_reply_reads_its_lines(self) -> None:
        call = TOOL_CALL_MARKER + '{"name": "search_chats", "arguments": {"query": "shaadi", "person": "Farheen"}}'
        writer = AsyncMock(return_value="Haan, uski shaadi fix ho gayi hai.")
        with patch("agent.runtime.orchestrator.generate_agent_reply", writer):
            reply, info = await _answer_with_search(call, user_id=USER_ID, reply_messages=[{"role": "user", "content": "farheen ki shaadi?"}], generation_arguments={"model": "m"})

        self.assertEqual(reply, "Haan, uski shaadi fix ho gayi hai.")
        self.assertEqual((info["query"], info["person"], info["hits"]), ("shaadi", "Farheen", 1))
        note = writer.await_args.args[0][-1]
        self.assertEqual(note["role"], "system")
        self.assertIn("Farheen: my shaadi is fixed", note["content"])
        self.assertNotIn("tools", writer.await_args.kwargs)

    async def test_a_plain_reply_passes_through(self) -> None:
        reply, info = await _answer_with_search("Hey!", user_id=USER_ID, reply_messages=[], generation_arguments={})
        self.assertEqual((reply, info), ("Hey!", None))

    def test_tool_calls_are_told_apart_from_replies(self) -> None:
        self.assertEqual(parse_tool_call(TOOL_CALL_MARKER + '{"name": "search_chats", "arguments": {"query": "x"}}'), ("search_chats", {"query": "x"}))
        self.assertIsNone(parse_tool_call('{"query": "x"}'))
        self.assertEqual(SEARCH_TOOL["function"]["name"], "search_chats")


if __name__ == "__main__":
    unittest.main()
