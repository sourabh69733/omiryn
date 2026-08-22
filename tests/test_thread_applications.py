"""Verifies exactly-once persistence of validated background thread operations."""

from __future__ import annotations

import importlib
import unittest

from agent.context_engine.conversation_engine.state import (
    ConversationState,
    create_thread,
    evaluate_thread_operation_shadow,
    get_state,
    get_thread,
    list_threads,
    save_state,
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
        self.assertEqual(get_state(self.conversation_id, self.user_id).version, 1)

    def test_create_sets_the_new_thread_as_active_for_the_processed_message(self) -> None:
        proposal = evaluate_thread_operation_shadow(
            {
                "operation": "create",
                "title": "Career change",
                "summary": "The user is considering a career change.",
                "origin": "user_started",
                "user_interest": "high",
            },
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            message_index=4,
            candidate_thread_ids=set(),
        )["proposal"]

        result = self._application_function()(
            batch_key="batch-activate-create",
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            message_index=4,
            proposal=proposal,
        )

        state = get_state(self.conversation_id, self.user_id)
        self.assertIsNotNone(state)
        self.assertEqual(state.active_thread_id, result.thread_id)
        self.assertEqual(state.state_through_message_index, 4)

    def test_switch_replaces_the_active_thread(self) -> None:
        previous = create_thread(
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            title="Previous subject",
            summary="The conversation was previously focused here.",
            origin="user_started",
        )
        replacement = create_thread(
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            title="New subject",
            summary="The user moved to another meaningful subject.",
            origin="user_started",
        )
        save_state(
            ConversationState(
                conversation_id=self.conversation_id,
                user_id=self.user_id,
                state_through_message_index=2,
                active_thread_id=previous.id,
            )
        )
        proposal = evaluate_thread_operation_shadow(
            {"operation": "switch", "thread_id": replacement.id},
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            message_index=6,
            candidate_thread_ids={previous.id, replacement.id},
        )["proposal"]

        self._application_function()(
            batch_key="batch-switch-active",
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            message_index=6,
            proposal=proposal,
        )

        state = get_state(self.conversation_id, self.user_id)
        self.assertEqual(state.active_thread_id, replacement.id)
        self.assertEqual(state.state_through_message_index, 6)

    def test_closing_operations_clear_the_active_thread_atomically(self) -> None:
        expected_status = {
            "pause": "paused",
            "complete": "completed",
            "block": "blocked_by_user",
        }
        for index, (operation, status) in enumerate(expected_status.items(), start=1):
            with self.subTest(operation=operation):
                conversation_id = f"{self.conversation_id}-{operation}"
                save_conversation(
                    {"id": conversation_id, "status": "active", "messages": []},
                    self.user_id,
                )
                thread = create_thread(
                    user_id=self.user_id,
                    conversation_id=conversation_id,
                    title=f"Subject to {operation}",
                    summary="This subject currently owns the active pointer.",
                    origin="user_started",
                )
                save_state(
                    ConversationState(
                        conversation_id=conversation_id,
                        user_id=self.user_id,
                        state_through_message_index=2,
                        active_thread_id=thread.id,
                    )
                )
                proposal = evaluate_thread_operation_shadow(
                    {"operation": operation, "thread_id": thread.id},
                    conversation_id=conversation_id,
                    user_id=self.user_id,
                    message_index=4 + index,
                    candidate_thread_ids={thread.id},
                )["proposal"]

                self._application_function()(
                    batch_key=f"batch-{operation}-active",
                    conversation_id=conversation_id,
                    user_id=self.user_id,
                    message_index=4 + index,
                    proposal=proposal,
                )

                state = get_state(conversation_id, self.user_id)
                self.assertIsNone(state.active_thread_id)
                self.assertEqual(state.state_through_message_index, 4 + index)
                self.assertEqual(get_thread(thread.id, self.user_id).status, status)

    def test_continue_across_conversations_activates_the_current_session(self) -> None:
        previous_conversation = "thread-application-previous-conversation"
        save_conversation(
            {"id": previous_conversation, "status": "active", "messages": []},
            self.user_id,
        )
        thread = create_thread(
            user_id=self.user_id,
            conversation_id=previous_conversation,
            title="Career change",
            summary="The user started discussing a career change earlier.",
            origin="user_started",
            user_interest="high",
        )
        proposal = evaluate_thread_operation_shadow(
            {
                "operation": "continue",
                "thread_id": thread.id,
                "summary": "The user returned to the career change decision.",
            },
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            message_index=8,
            candidate_thread_ids={thread.id},
        )["proposal"]

        self._application_function()(
            batch_key="batch-cross-session-continue",
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            message_index=8,
            proposal=proposal,
        )

        state = get_state(self.conversation_id, self.user_id)
        self.assertEqual(state.active_thread_id, thread.id)
        self.assertEqual(state.state_through_message_index, 8)
        self.assertEqual(
            get_thread(thread.id, self.user_id).last_conversation_id,
            self.conversation_id,
        )

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
