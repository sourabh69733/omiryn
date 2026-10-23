"""When a draft says Omi does not know, it searches first; a question about someone stays on them."""

import os
import unittest
from unittest.mock import AsyncMock, patch

from agent.context_engine.assembly.sources import build_reply_context_sources
from agent.context_engine.conversation_engine.policy.unknown import says_unknown
from agent.runtime.orchestrator import _search_when_unsure
from storage import reset_db, save_conversation, set_user_timezone
from storage.upload_digests import save_upload_digest

USER_ID = "unsure-user"


class SaysUnknownTest(unittest.TestCase):
    def test_dont_know_drafts_in_english_and_hinglish(self) -> None:
        for draft in ("I don't have information about that.", "I don't know about her relationship status.", "Mujhe nahi pata yaar", "Yeh chat mein mention nahi hua", "Pata nahi, tum batao"):
            self.assertTrue(says_unknown(draft), draft)

    def test_ordinary_replies_are_not_unknown(self) -> None:
        for draft in ("Haan, uski engagement fix hai!", "I know right, that trek sounds fun.", "Nahi yaar, aaj nahi."):
            self.assertFalse(says_unknown(draft), draft)


class SearchWhenUnsureTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        set_user_timezone(USER_ID, "Asia/Kolkata")
        save_conversation(
            {"id": "upload", "status": "active", "import_source_id": "src", "messages": [{"role": "other", "speaker": "Farheen", "content": "decided to do engagement next year", "created_at": "2026-10-08T16:36:00+00:00"}]},
            USER_ID,
        )
        save_conversation({"id": "omi", "status": "active", "messages": [{"role": "assistant", "content": "I don't know about her engagement."}]}, USER_ID)

    async def _run(self, query: str):
        writer = AsyncMock(return_value="Haan, usne engagement decide kar li hai, next year.")
        with patch.dict(os.environ, {"MEMORY_EMBEDDING_MODEL": "off"}), patch("agent.runtime.orchestrator.generate_agent_reply", writer):
            result = await _search_when_unsure("I don't have information about that.", user_id=USER_ID, conversation_id="omi", query=query, message_count=1, reply_messages=[], generation_arguments={})
        return result, writer

    async def test_found_lines_rewrite_the_reply(self) -> None:
        (reply, info), writer = await self._run("is she going to get engaged?")
        self.assertEqual(reply, "Haan, usne engagement decide kar li hai, next year.")
        self.assertEqual(info["hits"], 1)
        self.assertIn("Farheen: decided to do engagement next year", writer.await_args.args[0][-1]["content"])

    async def test_nothing_found_keeps_the_honest_draft(self) -> None:
        (reply, info), writer = await self._run("what is her favourite movie")
        self.assertEqual(reply, "I don't have information about that.")
        self.assertEqual(info["hits"], 0)
        writer.assert_not_awaited()


class OneSubjectTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": "chat", "status": "active", "messages": []}, USER_ID)
        save_conversation({"id": "upload", "status": "active", "import_source_id": "src", "messages": []}, USER_ID)
        save_upload_digest("src", USER_ID, "upload", "Farheen Parvez", {"index_line": "work"})

    def test_a_question_about_someone_gets_no_unrelated_memories(self) -> None:
        with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"}), patch(
            "agent.context_engine.assembly.sources._might_fit_sources", return_value=[{"source_type": "might_fit", "content": "Likes Harry Potter"}]
        ) as might_fit:
            build_reply_context_sources("chat", None, "what is farheen doing these days?", USER_ID)
            might_fit.assert_not_called()
            build_reply_context_sources("chat", None, "kya chal raha hai", USER_ID)
            might_fit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
