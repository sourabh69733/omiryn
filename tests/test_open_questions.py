"""When unsure, background cognition asks instead of guessing; Omi asks when it fits; answers close it."""

import json
import os
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agent.cognition.background.service import run_background_cognition
from agent.context_engine.assembly.sources import OPEN_QUESTION_REPLIES_PER_SESSION, _open_question_sources
from agent.memory_engine.memories.open_questions import validate_open_questions
from agent.memory_engine.processing import build_memory_batch
from agent.shared.clock import utc_now
from storage import (
    add_open_questions,
    delete_conversation,
    list_open_questions,
    reset_db,
    save_conversation,
)

USER_ID = "open-question-user"
CHAT = "open-question-chat"
MESSAGES = [
    {"role": "user", "content": "Reached <place>, so tired."},
    {"role": "assistant", "content": "Long day?"},
]


def _response(open_questions: object) -> dict:
    return {
        "decision": "no_change",
        "operations": [],
        "thread_operation": {"operation": "none"},
        "handoff": {"summary": "", "active_people": [], "active_topics": [], "unresolved_references": []},
        "open_questions": open_questions,
    }


def _question(question_id: str = "q1", text: str = "Did they move, or are they only visiting?") -> dict:
    return {"id": question_id, "text": text, "message_index": 0}


class ValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.batch = build_memory_batch(conversation_id=CHAT, user_id=USER_ID, messages=MESSAGES)

    def _validate(self, raw: object, open_ids: set[str] = frozenset()) -> object:
        return validate_open_questions(raw, batch=self.batch, open_question_ids=set(open_ids), memory_ids={"m1"})

    def test_a_question_must_come_from_a_new_user_message(self) -> None:
        good = self._validate([{"operation": "add", "text": "Moved?", "message_index": 0, "about_memory_ids": ["m1", "ghost"]}])
        from_omi = self._validate([{"operation": "add", "text": "Moved?", "message_index": 1}])

        self.assertEqual(good.adds[0].about_memory_ids, ("m1",))
        self.assertEqual(from_omi.adds, ())

    def test_one_new_question_per_batch_and_only_open_ones_resolve(self) -> None:
        changes = self._validate(
            [
                {"operation": "add", "text": "One?", "message_index": 0},
                {"operation": "add", "text": "Two?", "message_index": 0},
                {"operation": "resolve", "target_question_id": "q1", "status": "answered"},
                {"operation": "resolve", "target_question_id": "closed", "status": "answered"},
            ],
            open_ids={"q1"},
        )

        self.assertEqual([add.text for add in changes.adds], ["One?"])
        self.assertEqual([item.question_id for item in changes.resolves], ["q1"])
        self.assertEqual(len(changes.dropped), 2)


class BackgroundFlowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": CHAT, "status": "active", "messages": MESSAGES}, USER_ID)
        self.env = patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    async def _run(self, open_questions: object, messages: list[dict]) -> AsyncMock:
        save_conversation({"id": CHAT, "status": "active", "messages": messages}, USER_ID)
        with patch(
            "agent.cognition.background.service.analyze_background_cognition",
            new_callable=AsyncMock,
            return_value=_response(open_questions),
        ) as provider:
            await run_background_cognition(CHAT, USER_ID, messages)
        return provider

    async def test_a_doubt_is_saved_then_closed_by_the_answer(self) -> None:
        await self._run([{"operation": "add", "text": "Did they move, or only visiting?", "message_index": 0}], MESSAGES)
        [question] = list_open_questions(USER_ID)
        self.assertEqual(question["text"], "Did they move, or only visiting?")

        answered = MESSAGES + [{"role": "user", "content": "Just visiting for a wedding."}]
        provider = await self._run(
            [{"operation": "resolve", "target_question_id": question["id"], "status": "answered"}], answered
        )

        payload = json.loads(provider.await_args.args[0])
        self.assertEqual(payload["open_questions"][0]["id"], question["id"])
        self.assertEqual(list_open_questions(USER_ID), [])


class ReplySideTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": CHAT, "status": "active", "messages": MESSAGES}, USER_ID)
        self.env = patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3"})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def test_a_session_sees_the_question_a_few_times_then_it_waits(self) -> None:
        add_open_questions(USER_ID, CHAT, [_question()])

        seen = [bool(_open_question_sources(CHAT, USER_ID)) for _ in range(OPEN_QUESTION_REPLIES_PER_SESSION + 1)]

        self.assertEqual(seen, [True] * OPEN_QUESTION_REPLIES_PER_SESSION + [False])
        self.assertIn("only if it fits naturally", _open_question_sources("other-chat", USER_ID)[0]["content"])

    def test_expired_questions_are_not_shown(self) -> None:
        add_open_questions(USER_ID, CHAT, [_question()])

        self.assertEqual(list_open_questions(USER_ID, now=utc_now() + timedelta(days=15)), [])

    def test_deleting_the_chat_deletes_its_questions(self) -> None:
        add_open_questions(USER_ID, CHAT, [_question()])

        delete_conversation(CHAT, USER_ID)

        self.assertEqual(list_open_questions(USER_ID), [])


class ApiTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        from api.main import app
        from security.auth import CurrentUser, require_user

        app.dependency_overrides[require_user] = lambda: CurrentUser(id=USER_ID, email="q@example.com", display_name="Q")
        self.app = app
        self.client = TestClient(app)
        save_conversation({"id": CHAT, "status": "active", "messages": MESSAGES}, USER_ID)
        add_open_questions(USER_ID, CHAT, [_question()])

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()

    def test_the_user_can_see_and_dismiss_a_question(self) -> None:
        listed = self.client.get("/api/me/open-questions").json()["questions"]

        self.assertEqual([item["id"] for item in listed], ["q1"])
        self.assertEqual(self.client.post("/api/me/open-questions/q1/dismiss").status_code, 200)
        self.assertEqual(self.client.post("/api/me/open-questions/q1/dismiss").status_code, 404)
        self.assertEqual(self.client.get("/api/me/open-questions").json()["questions"], [])


if __name__ == "__main__":
    unittest.main()
