"""Threads come from the user's own words, expire across chats, and go with their chat."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import update

from agent.context_engine.conversation_engine.state import create_thread, get_thread, list_threads
from agent.context_engine.conversation_engine.state.context import (
    _carries_across_chats,
    conversation_thread_guidance,
)
from agent.context_engine.conversation_engine.state.shadow import evaluate_thread_operation_shadow
from storage import (
    delete_conversation,
    prune_threads_from_missing_chats,
    reset_db,
    save_conversation,
)
from storage.database import ENGINE
from storage.schema import agent_conversations, conversation_threads

USER_ID = "thread-hygiene-user"
FIRST = "thread-hygiene-first"
SECOND = "thread-hygiene-second"
ROLES = {0: "assistant", 1: "user", 2: "assistant", 3: "user"}


def _save(conversation_id: str) -> None:
    save_conversation(
        {"id": conversation_id, "status": "active", "messages": [{"role": "user", "content": "hi"}]},
        USER_ID,
    )


def _thread(conversation_id: str, title: str, origin: str = "user_started"):
    return create_thread(
        user_id=USER_ID,
        conversation_id=conversation_id,
        title=title,
        summary=f"The user talked about {title.lower()}.",
        origin=origin,
        user_interest="high",
    )


class ThreadOriginTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        _save(FIRST)

    def _evaluate(self, operation: dict, candidates: set[str] = frozenset()) -> dict:
        return evaluate_thread_operation_shadow(
            operation,
            conversation_id=FIRST,
            user_id=USER_ID,
            message_index=3,
            candidate_thread_ids=set(candidates),
            message_roles=ROLES,
        )

    def _create(self, **fields) -> dict:
        return self._evaluate({"operation": "create", "title": "Guitar", "summary": "Learning guitar.", **fields})

    def test_origin_comes_from_who_wrote_the_start_message(self) -> None:
        for started_at, origin in ((0, "agent_started"), (1, "user_started")):
            with self.subTest(started_at=started_at):
                result = self._create(started_at=started_at, evidence=[1], origin="user_started")
                self.assertTrue(result["valid"], result["errors"])
                self.assertEqual(result["proposal"]["thread_updates"][0]["thread"]["origin"], origin)

    def test_no_user_message_means_no_thread(self) -> None:
        for evidence in (None, [], [0, 2], [99], [True]):
            with self.subTest(evidence=evidence):
                self.assertFalse(self._create(started_at=1, evidence=evidence)["valid"])
        self.assertFalse(self._create(started_at=99, evidence=[1])["valid"])

    def test_high_interest_needs_the_users_words(self) -> None:
        thread = _thread(FIRST, "Guitar")
        base = {"operation": "continue", "thread_id": thread.id, "user_interest": "high"}

        without = self._evaluate(base, {thread.id})["proposal"]["thread_updates"][0]["changes"]
        with_proof = self._evaluate({**base, "evidence": [3]}, {thread.id})["proposal"]["thread_updates"][0]["changes"]

        self.assertNotIn("user_interest", without)
        self.assertEqual(with_proof["user_interest"], "high")


class CrossChatThreadTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        _save(FIRST)
        _save(SECOND)

    def _offered(self, text: str) -> set[str]:
        with patch.dict("os.environ", {"AGENT_PIPELINE_VERSION": "v2", "AGENT_ROLLOUT": "shadow"}):
            guidance = conversation_thread_guidance(SECOND, USER_ID, text)
        return {reference.id for reference in guidance.relevant_open}

    def test_only_the_users_own_fresh_topics_come_back_in_another_chat(self) -> None:
        own = _thread(FIRST, "Tech interview prep")
        agent = _thread(FIRST, "Tech interview tips", origin="agent_started")

        offered = self._offered("my tech interview prep")

        self.assertIn(own.id, offered)
        self.assertNotIn(agent.id, offered)

    def test_old_topics_from_other_chats_expire(self) -> None:
        thread = get_thread(_thread(FIRST, "Tech interview prep").id, USER_ID)
        now = datetime.now(UTC)
        stale = replace(thread, updated_at=(now - timedelta(days=15)).isoformat())

        self.assertTrue(_carries_across_chats(thread, now))
        self.assertFalse(_carries_across_chats(stale, now))


class ThreadDeletionTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        _save(FIRST)
        _save(SECOND)

    def test_deleting_a_chat_drops_its_own_topics_only(self) -> None:
        only_here = _thread(FIRST, "Tech interview prep")
        moved_on = _thread(FIRST, "Guitar")
        with ENGINE.begin() as connection:
            connection.execute(
                update(conversation_threads)
                .where(conversation_threads.c.id == moved_on.id)
                .values(last_conversation_id=SECOND)
            )

        delete_conversation(FIRST, USER_ID)

        self.assertEqual({thread.id for thread in list_threads(USER_ID)}, {moved_on.id})

    def test_topics_left_by_chats_deleted_earlier_are_pruned(self) -> None:
        orphan = _thread(FIRST, "Tech interview prep")
        kept = _thread(SECOND, "Guitar")
        with ENGINE.begin() as connection:
            connection.execute(agent_conversations.delete().where(agent_conversations.c.id == FIRST))

        self.assertEqual(prune_threads_from_missing_chats(USER_ID), 1)
        self.assertEqual({thread.id for thread in list_threads(USER_ID)}, {kept.id})
        self.assertIsNone(get_thread(orphan.id, USER_ID))

    def test_delete_dialog_lists_the_topics_that_go(self) -> None:
        from api.main import app
        from security.auth import CurrentUser, require_user

        _thread(FIRST, "Tech interview prep")
        app.dependency_overrides[require_user] = lambda: CurrentUser(
            id=USER_ID, email="thread@example.com", display_name="Thread"
        )
        try:
            body = TestClient(app).get(f"/api/agent/conversations/{FIRST}/deletion-impact").json()
        finally:
            app.dependency_overrides.clear()

        self.assertEqual(body["topics_dropped"], ["Tech interview prep"])


if __name__ == "__main__":
    unittest.main()
