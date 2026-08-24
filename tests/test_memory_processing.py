"""Verifies Phase 1 batching, cross-batch context, privacy, and cursor safety."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import unittest
from dataclasses import replace
from unittest.mock import patch

from sqlalchemy import select

from agent.memory_engine.processing import (
    MemoryHandoff,
    MemoryProcessingState,
    build_memory_batch,
    claim_processing_batch,
    get_processing_state,
    release_processing_batch,
    save_processing_state,
)
from agent.memory_engine.processing.service import MemoryProcessingStateConflictError
from security.encryption import is_encrypted_blob
from storage import ENGINE, delete_conversation, reset_db, save_conversation
from storage.schema import memory_processing_leases, memory_processing_states


class MemoryProcessingTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        self.user_id = "memory-user"
        self.conversation_id = "memory-conversation"
        self.messages = [
            {"role": "user", "content": "My friend Priya moved to Chennai."},
            {"role": "assistant", "content": "That sounds like a meaningful change."},
            {"role": "user", "content": "She is calm and very funny."},
            {"role": "assistant", "content": "You seem to value that combination."},
            {"role": "user", "content": "That is the kind of person I prefer."},
            {"role": "assistant", "content": "I understand."},
        ]
        self._save_conversation(self.messages)

    def test_batch_carries_previous_context_without_reusing_it_as_evidence(self) -> None:
        state = MemoryProcessingState(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            processed_through_message_index=1,
            handoff=MemoryHandoff(
                summary="The user introduced Priya, who moved to Chennai.",
                active_people=("Priya",),
                active_topics=("partner personality",),
            ),
        )

        batch = build_memory_batch(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            messages=self.messages,
            state=state,
            context_overlap=2,
            max_meaningful_user_messages=2,
        )

        self.assertIsNotNone(batch)
        assert batch is not None
        self.assertEqual([message.message_index for message in batch.context_messages], [0, 1])
        self.assertEqual([message.message_index for message in batch.new_messages], [2, 3, 4, 5])
        self.assertEqual(batch.evidence_message_indexes, (2, 4))
        self.assertEqual(batch.previous_handoff.active_people, ("Priya",))
        self.assertFalse(any(message.evidence_eligible for message in batch.context_messages))

    def test_batch_limit_uses_meaningful_user_messages_and_keeps_interleaved_context(self) -> None:
        messages: list[dict[str, object]] = []
        for index in range(8):
            messages.extend(
                [
                    {"role": "user", "content": f"Meaningful detail {index}"},
                    {"role": "assistant", "content": f"Reply {index}"},
                ]
            )
        messages[2]["quality"] = "simple_acknowledgement"

        batch = build_memory_batch(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            messages=messages,
            max_meaningful_user_messages=7,
        )

        self.assertIsNotNone(batch)
        assert batch is not None
        self.assertEqual(batch.meaningful_user_message_count, 7)
        self.assertEqual(batch.new_end_message_index, 15)
        self.assertEqual([message.message_index for message in batch.new_messages], list(range(16)))

    def test_same_messages_produce_stable_batch_key_and_cursor_removes_processed_work(self) -> None:
        first = build_memory_batch(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            messages=self.messages,
        )
        repeated = build_memory_batch(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            messages=self.messages,
        )
        self.assertIsNotNone(first)
        self.assertEqual(first, repeated)
        assert first is not None

        completed = MemoryProcessingState(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            processed_through_message_index=first.new_end_message_index,
            last_batch_key=first.batch_key,
        )
        self.assertIsNone(
            build_memory_batch(
                conversation_id=self.conversation_id,
                user_id=self.user_id,
                messages=self.messages,
                state=completed,
            )
        )

    def test_zero_overlap_and_foreign_state_are_rejected_safely(self) -> None:
        state = MemoryProcessingState(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            processed_through_message_index=1,
        )
        batch = build_memory_batch(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            messages=self.messages,
            state=state,
            context_overlap=0,
        )
        self.assertIsNotNone(batch)
        assert batch is not None
        self.assertEqual(batch.context_messages, ())

        with self.assertRaises(ValueError):
            build_memory_batch(
                conversation_id=self.conversation_id,
                user_id="another-user",
                messages=self.messages,
                state=state,
            )

    def test_processing_state_is_owned_optimistic_and_idempotent(self) -> None:
        initial = MemoryProcessingState(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            processed_through_message_index=4,
            last_batch_key="batch-one",
            handoff=MemoryHandoff(summary="Priya is the active person."),
        )
        saved = save_processing_state(initial)
        self.assertEqual(saved.version, 1)
        self.assertEqual(get_processing_state(self.conversation_id, self.user_id), saved)
        self.assertIsNone(get_processing_state(self.conversation_id, "another-user"))

        retried = save_processing_state(initial)
        self.assertEqual(retried, saved)

        advanced = save_processing_state(
            replace(
                saved,
                processed_through_message_index=7,
                last_batch_key="batch-two",
            )
        )
        self.assertEqual(advanced.version, 2)
        with self.assertRaises(MemoryProcessingStateConflictError):
            save_processing_state(
                replace(
                    saved,
                    processed_through_message_index=8,
                    last_batch_key="stale-batch",
                )
            )

    def test_processing_batch_lease_allows_only_one_owner(self) -> None:
        first_owner = claim_processing_batch(
            self.conversation_id,
            self.user_id,
            "batch-one",
            expected_processed_index=-1,
            lease_seconds=60,
        )
        second_owner = claim_processing_batch(
            self.conversation_id,
            self.user_id,
            "batch-one",
            expected_processed_index=-1,
            lease_seconds=60,
        )

        self.assertIsNotNone(first_owner)
        self.assertIsNone(second_owner)
        assert first_owner is not None
        self.assertFalse(
            release_processing_batch("batch-one", self.user_id, "wrong-owner")
        )
        self.assertTrue(
            release_processing_batch("batch-one", self.user_id, first_owner)
        )

    def test_processing_batch_lease_rejects_a_stale_cursor(self) -> None:
        save_processing_state(
            MemoryProcessingState(
                conversation_id=self.conversation_id,
                user_id=self.user_id,
                processed_through_message_index=2,
                last_batch_key="completed-batch",
            )
        )

        owner = claim_processing_batch(
            self.conversation_id,
            self.user_id,
            "stale-batch",
            expected_processed_index=-1,
            lease_seconds=60,
        )

        self.assertIsNone(owner)
        with ENGINE.begin() as connection:
            lease_count = connection.execute(
                select(memory_processing_leases.c.batch_key)
            ).all()
        self.assertEqual(lease_count, [])

    def test_expired_processing_batch_lease_can_be_reclaimed(self) -> None:
        first_owner = claim_processing_batch(
            self.conversation_id,
            self.user_id,
            "expired-batch",
            expected_processed_index=-1,
            lease_seconds=60,
        )
        self.assertIsNotNone(first_owner)
        with ENGINE.begin() as connection:
            connection.execute(
                memory_processing_leases.update()
                .where(memory_processing_leases.c.batch_key == "expired-batch")
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )

        second_owner = claim_processing_batch(
            self.conversation_id,
            self.user_id,
            "expired-batch",
            expected_processed_index=-1,
            lease_seconds=60,
        )

        self.assertIsNotNone(second_owner)
        self.assertNotEqual(second_owner, first_owner)
        assert first_owner is not None
        assert second_owner is not None
        self.assertFalse(
            release_processing_batch("expired-batch", self.user_id, first_owner)
        )
        self.assertTrue(
            release_processing_batch("expired-batch", self.user_id, second_owner)
        )

    def test_handoff_is_encrypted_at_rest_and_removed_with_conversation(self) -> None:
        encryption_key = base64.urlsafe_b64encode(b"m" * 32).decode("ascii")
        with patch.dict("os.environ", {"ENCRYPTION_MASTER_KEY": encryption_key}):
            saved = save_processing_state(
                MemoryProcessingState(
                    conversation_id=self.conversation_id,
                    user_id=self.user_id,
                    processed_through_message_index=2,
                    last_batch_key="private-batch",
                    handoff=MemoryHandoff(summary="A private relationship story."),
                )
            )
            with ENGINE.begin() as connection:
                raw = connection.execute(
                    select(memory_processing_states.c.handoff_json).where(
                        memory_processing_states.c.conversation_id == self.conversation_id
                    )
                ).scalar_one()
            lease_owner = claim_processing_batch(
                self.conversation_id,
                self.user_id,
                "private-batch-lease",
                expected_processed_index=2,
                lease_seconds=60,
            )
            self.assertIsNotNone(lease_owner)
            self.assertTrue(is_encrypted_blob(raw))
            self.assertEqual(saved.handoff.summary, "A private relationship story.")
            self.assertTrue(delete_conversation(self.conversation_id, self.user_id))
            self.assertIsNone(get_processing_state(self.conversation_id, self.user_id))
            with ENGINE.begin() as connection:
                remaining_lease = connection.execute(
                    select(memory_processing_leases.c.batch_key)
                ).first()
            self.assertIsNone(remaining_lease)

    def _save_conversation(self, messages: list[dict[str, object]]) -> None:
        save_conversation(
            {
                "id": self.conversation_id,
                "status": "active",
                "messages": messages,
            },
            self.user_id,
        )


if __name__ == "__main__":
    unittest.main()
