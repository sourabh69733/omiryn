"""Verifies exactly-once persistence of validated background thread operations."""

from __future__ import annotations

import importlib
import unittest

from agent.context_engine.conversation_engine.state import (
    create_thread,
    evaluate_thread_operation_shadow,
    get_thread,
    list_threads,
)
from storage import reset_db, save_conversation


class ThreadApplicationTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        self.user_id = "thread-application-user"
        self.conversation_id = "thread-application-conversation"
        save_conversation(
            {"id": self.conversation_id, "status": "active", "messages": []},
            self.user_id,
        )

    def test_create_is_applied_exactly_once_per_batch(self) -> None:
        proposal = evaluate_thread_operation_shadow(
            {
                "operation": "create",
                "title": "Career change",
                "summary": "The user is considering a career change.",
                "origin": "user_started",
                "depth": "mentioned",
                "user_interest": "high",
                "salience": 0.8,
            },
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            message_index=4,
            candidate_thread_ids=set(),
        )["proposal"]

        apply = self._application_function()
        first = apply(
            batch_key="batch-create",
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            message_index=4,
            proposal=proposal,
        )
        repeated = apply(
            batch_key="batch-create",
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            message_index=4,
            proposal=proposal,
        )

        self.assertEqual(first.applied_count, 1)
        self.assertFalse(first.idempotent)
        self.assertTrue(repeated.idempotent)
        self.assertEqual(first.thread_id, repeated.thread_id)
        self.assertEqual(len(list_threads(self.user_id)), 1)

    def test_update_is_applied_once_and_changed_retry_is_rejected(self) -> None:
        thread = create_thread(
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            title="Career change",
            summary="The user is considering a career change.",
            origin="user_started",
            message_index=1,
        )
        proposal = evaluate_thread_operation_shadow(
            {
                "operation": "continue",
                "thread_id": thread.id,
                "summary": "The user is worried about financial stability.",
                "depth": "explored",
            },
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            message_index=6,
            candidate_thread_ids={thread.id},
        )["proposal"]

        apply = self._application_function()
        first = apply(
            batch_key="batch-update",
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            message_index=6,
            proposal=proposal,
        )
        repeated = apply(
            batch_key="batch-update",
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            message_index=6,
            proposal=proposal,
        )

        self.assertEqual(first.applied_count, 1)
        self.assertTrue(repeated.idempotent)
        self.assertEqual(get_thread(thread.id, self.user_id).version, 2)

        changed = {
            **proposal,
            "thread_updates": [
                {
                    **proposal["thread_updates"][0],
                    "changes": {
                        **proposal["thread_updates"][0]["changes"],
                        "summary": "A different retry payload.",
                    },
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "does not match"):
            apply(
                batch_key="batch-update",
                conversation_id=self.conversation_id,
                user_id=self.user_id,
                message_index=6,
                proposal=changed,
            )

    def _application_function(self):
        module = importlib.import_module(
            "agent.context_engine.conversation_engine.state.application"
        )
        function = getattr(module, "apply_validated_thread_proposal", None)
        self.assertTrue(callable(function), "apply_validated_thread_proposal is missing")
        return function


if __name__ == "__main__":
    unittest.main()
