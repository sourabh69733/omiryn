"""Covers persistence, ownership, lifecycle validation, and optimistic state safety."""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from agent.context_engine.engine import build_model_context_package
from agent.context_engine.conversation_engine.state import (
    ConversationState,
    ConversationStateConflictError,
    ConversationStateValidationError,
    create_thread,
    evaluate_conversation_update_shadow,
    get_state,
    get_thread,
    list_threads,
    save_state,
    update_thread,
)
from storage import reset_db, save_conversation


class ConversationThreadStateTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        self.user_id = "thread-user"
        self.first_conversation = "conversation-one"
        self.second_conversation = "conversation-two"
        self._save_conversation(self.first_conversation, self.user_id)
        self._save_conversation(self.second_conversation, self.user_id)
        self._save_conversation("other-user-conversation", "other-user")

    def test_thread_can_continue_across_conversations_without_duplication(self) -> None:
        thread = create_thread(
            user_id=self.user_id,
            conversation_id=self.first_conversation,
            title="Stress with manager",
            summary="The user's manager changes plans frequently.",
            origin="user_started",
            user_interest="high",
            message_index=2,
        )

        updated = update_thread(
            thread.id,
            self.user_id,
            {
                "last_conversation_id": self.second_conversation,
                "summary": "The user values clarity and returned to the manager story.",
                "depth": "explored",
                "last_message_index": 4,
            },
            expected_version=thread.version,
        )

        self.assertEqual(updated.created_in_conversation_id, self.first_conversation)
        self.assertEqual(updated.last_conversation_id, self.second_conversation)
        self.assertEqual(updated.depth, "explored")
        self.assertEqual(updated.version, 2)
        self.assertEqual([row.id for row in list_threads(self.user_id)], [thread.id])
        self.assertEqual(
            [
                row.id
                for row in list_threads(self.user_id, conversation_id=self.second_conversation)
            ],
            [thread.id],
        )

    def test_state_has_one_active_pointer_and_rejects_stale_updates(self) -> None:
        thread = create_thread(
            user_id=self.user_id,
            conversation_id=self.first_conversation,
            title="Career support",
            summary="The user wants a partner who supports their career.",
            origin="user_started",
        )
        state = save_state(
            ConversationState(
                conversation_id=self.first_conversation,
                user_id=self.user_id,
                state_through_message_index=3,
                active_thread_id=thread.id,
                user_need="explore",
                session_goal="Understand what support means to the user.",
            )
        )
        self.assertEqual(state.version, 1)
        self.assertEqual(get_state(self.first_conversation, self.user_id), state)

        updated = save_state(
            replace(
                state,
                state_through_message_index=5,
                user_need="listen",
            )
        )
        self.assertEqual(updated.version, 2)
        with self.assertRaises(ConversationStateConflictError):
            save_state(replace(state, state_through_message_index=6))
        with self.assertRaises(ConversationStateConflictError):
            save_state(replace(updated, state_through_message_index=4))

    def test_closed_or_foreign_thread_cannot_become_active(self) -> None:
        closed = create_thread(
            user_id=self.user_id,
            conversation_id=self.first_conversation,
            title="Topic the user closed",
            summary="The user asked not to return to this subject.",
            origin="user_started",
            status="blocked_by_user",
        )
        foreign = create_thread(
            user_id="other-user",
            conversation_id="other-user-conversation",
            title="Private topic",
            summary="This belongs to another user.",
            origin="user_started",
        )
        for thread_id in (closed.id, foreign.id):
            with self.subTest(thread_id=thread_id):
                with self.assertRaises(ValueError):
                    save_state(
                        ConversationState(
                            conversation_id=self.first_conversation,
                            user_id=self.user_id,
                            active_thread_id=thread_id,
                        )
                    )
        self.assertIsNone(get_thread(foreign.id, self.user_id))

    def test_active_thread_must_be_cleared_before_it_is_paused(self) -> None:
        thread = create_thread(
            user_id=self.user_id,
            conversation_id=self.first_conversation,
            title="An unfinished story",
            summary="The user may want to continue this later.",
            origin="user_started",
        )
        state = save_state(
            ConversationState(
                conversation_id=self.first_conversation,
                user_id=self.user_id,
                active_thread_id=thread.id,
            )
        )
        with self.assertRaises(ValueError):
            update_thread(
                thread.id,
                self.user_id,
                {"status": "paused"},
                expected_version=thread.version,
            )

        save_state(replace(state, active_thread_id=None))
        paused = update_thread(
            thread.id,
            self.user_id,
            {"status": "paused"},
            expected_version=thread.version,
        )
        self.assertEqual(paused.status, "paused")

    def test_contract_rejects_semantically_unrestricted_but_structurally_invalid_data(self) -> None:
        with self.assertRaises(ConversationStateValidationError):
            create_thread(
                user_id=self.user_id,
                conversation_id=self.first_conversation,
                title="Invalid status",
                summary="The content is irrelevant to structural validation.",
                origin="user_started",
                status="active",
            )
        with self.assertRaises(ConversationStateValidationError):
            create_thread(
                user_id=self.user_id,
                conversation_id=self.first_conversation,
                title="Invalid salience",
                summary="The content is irrelevant to structural validation.",
                origin="user_started",
                salience=1.5,
            )

    def test_read_only_context_includes_active_and_current_open_threads(self) -> None:
        active = create_thread(
            user_id=self.user_id,
            conversation_id=self.second_conversation,
            title="Stress with manager",
            summary="Unclear communication at work is exhausting the user.",
            origin="user_started",
            next_angle="Understand whether this happens outside work too.",
        )
        save_state(
            ConversationState(
                conversation_id=self.first_conversation,
                user_id=self.user_id,
                active_thread_id=active.id,
            )
        )
        current_open = create_thread(
            user_id=self.user_id,
            conversation_id=self.first_conversation,
            title="Upcoming trip",
            summary="The user has an upcoming trip they may want to discuss.",
            origin="user_started",
        )
        blocked = create_thread(
            user_id=self.user_id,
            conversation_id=self.first_conversation,
            title="Blocked subject",
            summary="The user explicitly closed this subject.",
            origin="user_started",
            status="blocked_by_user",
        )
        unrelated = create_thread(
            user_id=self.user_id,
            conversation_id=self.second_conversation,
            title="Unrelated old chat",
            summary="This belongs to a different conversation and is not active.",
            origin="user_started",
        )

        with patch.dict("os.environ", {"CONVERSATION_STATE_V2_ENABLED": "true"}):
            package = self._context_package()

        source = next(
            item
            for item in package.context_sources
            if item.get("source_type") == "conversation_threads"
        )
        self.assertEqual(source["metadata"]["active_thread_id"], active.id)
        self.assertEqual(source["metadata"]["thread_ids"], [active.id, current_open.id])
        self.assertIn("Stress with manager", package.system_prompt)
        self.assertIn("Upcoming trip", package.system_prompt)
        self.assertNotIn(blocked.title, package.system_prompt)
        self.assertNotIn(unrelated.title, package.system_prompt)
        self.assertEqual(get_state(self.first_conversation, self.user_id).version, 1)
        self.assertEqual(get_thread(active.id, self.user_id).version, 1)
        self.assertEqual(get_thread(current_open.id, self.user_id).version, 1)

    def test_thread_context_is_capped_and_feature_flag_off_preserves_old_context(self) -> None:
        with patch.dict("os.environ", {"CONVERSATION_STATE_V2_ENABLED": "false"}):
            original = self._context_package()
        with patch.dict("os.environ", {"CONVERSATION_STATE_V2_ENABLED": "true"}):
            enabled_without_threads = self._context_package()
        self.assertEqual(enabled_without_threads.system_prompt, original.system_prompt)
        self.assertEqual(enabled_without_threads.context_sources, original.context_sources)

        for index in range(5):
            create_thread(
                user_id=self.user_id,
                conversation_id=self.first_conversation,
                title=f"Open subject {index}",
                summary=f"A resumable subject numbered {index}.",
                origin="user_started",
            )

        with patch.dict("os.environ", {"CONVERSATION_STATE_V2_ENABLED": "false"}):
            disabled = self._context_package()
        self.assertEqual(disabled.system_prompt, original.system_prompt)
        self.assertEqual(disabled.context_sources, original.context_sources)

        with patch.dict("os.environ", {"CONVERSATION_STATE_V2_ENABLED": "true"}):
            enabled = self._context_package()
        source = next(
            item
            for item in enabled.context_sources
            if item.get("source_type") == "conversation_threads"
        )
        self.assertEqual(source["metadata"]["thread_count"], 3)
        self.assertTrue(source["metadata"]["read_only"])

    def test_relevant_open_thread_from_previous_conversation_enters_context(self) -> None:
        prior = create_thread(
            user_id=self.user_id,
            conversation_id=self.second_conversation,
            title="Stress with manager",
            summary="The user's manager repeatedly changes priorities at work.",
            origin="user_started",
        )
        unrelated = create_thread(
            user_id=self.user_id,
            conversation_id=self.second_conversation,
            title="Weekend cooking",
            summary="The user considered trying a new pasta recipe.",
            origin="user_started",
        )

        with patch.dict("os.environ", {"CONVERSATION_STATE_V2_ENABLED": "true"}):
            package = self._context_package(
                user_text="That situation with my manager became worse today."
            )

        source = next(
            item
            for item in package.context_sources
            if item.get("source_type") == "conversation_threads"
        )
        self.assertIn(prior.id, source["metadata"]["thread_ids"])
        self.assertIn(prior.id, source["metadata"]["cross_session_thread_ids"])
        self.assertNotIn(unrelated.id, source["metadata"]["thread_ids"])
        self.assertIn("Stress with manager", package.system_prompt)
        self.assertNotIn("Weekend cooking", package.system_prompt)

    def test_shadow_proposal_is_validated_without_creating_a_thread(self) -> None:
        result = evaluate_conversation_update_shadow(
            {
                "user_need": "explore",
                "session_goal": "Understand the user's work experience.",
                "thread_updates": [
                    {
                        "operation": "create",
                        "title": "Stress with manager",
                        "summary": "The user is describing unclear communication at work.",
                        "origin": "user_started",
                        "depth": "mentioned",
                        "user_interest": "high",
                        "salience": 0.8,
                        "next_angle": "Understand what part feels most exhausting.",
                    }
                ],
            },
            conversation_id=self.first_conversation,
            user_id=self.user_id,
            message_index=2,
        )

        self.assertTrue(result["valid"])
        self.assertFalse(result["persisted"])
        self.assertEqual(result["proposed_thread_update_count"], 1)
        self.assertEqual(list_threads(self.user_id), [])

    def test_create_discards_model_generated_thread_id(self) -> None:
        result = evaluate_conversation_update_shadow(
            {
                "user_need": "explore",
                "thread_updates": [
                    {
                        "operation": "create",
                        "thread_id": "model-invented-id",
                        "title": "Stress with manager",
                        "summary": "The user is describing recurring stress at work.",
                        "origin": "user_started",
                    }
                ],
            },
            conversation_id=self.first_conversation,
            user_id=self.user_id,
            message_index=2,
        )

        self.assertTrue(result["valid"])
        created = result["proposal"]["thread_updates"][0]
        self.assertEqual(created["operation"], "create")
        self.assertNotIn("thread_id", created)
        self.assertEqual(list_threads(self.user_id), [])

    def test_shadow_explicit_none_normalizes_to_no_thread_updates(self) -> None:
        result = evaluate_conversation_update_shadow(
            {
                "user_need": "normal_chat",
                "thread_updates": [{"operation": "none"}],
            },
            conversation_id=self.first_conversation,
            user_id=self.user_id,
            message_index=2,
        )
        mixed = evaluate_conversation_update_shadow(
            {
                "user_need": "explore",
                "thread_updates": [
                    {"operation": "none"},
                    {
                        "operation": "create",
                        "title": "A real subject",
                        "summary": "A meaningful resumable subject.",
                        "origin": "user_started",
                    },
                ],
            },
            conversation_id=self.first_conversation,
            user_id=self.user_id,
            message_index=2,
        )

        self.assertTrue(result["valid"])
        self.assertEqual(result["proposal"]["thread_updates"], [])
        self.assertEqual(result["proposed_thread_update_count"], 0)
        self.assertFalse(mixed["valid"])
        self.assertTrue(any("none must be the only" in error for error in mixed["errors"]))

    def test_shadow_proposal_rejects_unknown_thread_and_multiple_creates(self) -> None:
        unknown = evaluate_conversation_update_shadow(
            {
                "user_need": "explore",
                "thread_updates": [{"operation": "continue", "thread_id": "not-owned"}],
            },
            conversation_id=self.first_conversation,
            user_id=self.user_id,
            message_index=2,
        )
        self.assertFalse(unknown["valid"])
        self.assertIn("owned thread_id", unknown["errors"][0])

        create = {
            "operation": "create",
            "title": "One meaningful subject",
            "summary": "A resumable discussion.",
            "origin": "user_started",
        }
        duplicate_create = evaluate_conversation_update_shadow(
            {
                "user_need": "explore",
                "thread_updates": [create, {**create, "title": "Second subject"}],
            },
            conversation_id=self.first_conversation,
            user_id=self.user_id,
            message_index=2,
        )
        self.assertFalse(duplicate_create["valid"])
        self.assertTrue(any("only one new" in error for error in duplicate_create["errors"]))

    def test_shadow_proposal_can_continue_open_thread_but_not_user_blocked_thread(self) -> None:
        open_thread = create_thread(
            user_id=self.user_id,
            conversation_id=self.first_conversation,
            title="Career uncertainty",
            summary="The user is considering a job change.",
            origin="user_started",
        )
        blocked_thread = create_thread(
            user_id=self.user_id,
            conversation_id=self.first_conversation,
            title="Private family subject",
            summary="The user asked not to revisit this.",
            origin="user_started",
            status="blocked_by_user",
        )
        continued = evaluate_conversation_update_shadow(
            {
                "user_need": "explore",
                "thread_updates": [
                    {
                        "operation": "continue",
                        "thread_id": open_thread.id,
                        "summary": "The user is now comparing two possible roles.",
                        "depth": "explored",
                    }
                ],
            },
            conversation_id=self.first_conversation,
            user_id=self.user_id,
            message_index=4,
        )
        self.assertTrue(continued["valid"])
        self.assertEqual(get_thread(open_thread.id, self.user_id).version, 1)

        blocked = evaluate_conversation_update_shadow(
            {
                "user_need": "explore",
                "thread_updates": [{"operation": "continue", "thread_id": blocked_thread.id}],
            },
            conversation_id=self.first_conversation,
            user_id=self.user_id,
            message_index=4,
        )
        self.assertFalse(blocked["valid"])
        self.assertTrue(any("cannot be changed" in error for error in blocked["errors"]))

    def test_existing_thread_allows_repeated_origin_but_rejects_origin_change(self) -> None:
        thread = create_thread(
            user_id=self.user_id,
            conversation_id=self.first_conversation,
            title="Career uncertainty",
            summary="The user is considering a job change.",
            origin="user_started",
        )
        base_update = {
            "user_need": "explore",
            "thread_updates": [
                {
                    "operation": "continue",
                    "thread_id": thread.id,
                    "origin": "user_started",
                }
            ],
        }

        repeated = evaluate_conversation_update_shadow(
            base_update,
            conversation_id=self.first_conversation,
            user_id=self.user_id,
            message_index=4,
        )
        changed = evaluate_conversation_update_shadow(
            {
                **base_update,
                "thread_updates": [
                    {
                        **base_update["thread_updates"][0],
                        "origin": "agent_started",
                    }
                ],
            },
            conversation_id=self.first_conversation,
            user_id=self.user_id,
            message_index=4,
        )

        self.assertTrue(repeated["valid"])
        self.assertFalse(changed["valid"])
        self.assertTrue(any("origin cannot be changed" in error for error in changed["errors"]))

    def _context_package(self, *, user_text: str = "Tell me something useful."):
        return build_model_context_package(
            conversation_id=self.first_conversation,
            user_text=user_text,
            user_id=self.user_id,
            user_profile={"user_id": self.user_id},
            model="mock-model",
            agent_tone="auto",
            agent_name="Omiryn",
            style_source_id=None,
            user_message_index=0,
            assistant_message_index=1,
            prompt_version_id="v3-1",
        )

    @staticmethod
    def _save_conversation(conversation_id: str, user_id: str) -> None:
        save_conversation(
            {
                "id": conversation_id,
                "status": "active",
                "messages": [],
            },
            user_id,
        )


if __name__ == "__main__":
    unittest.main()
