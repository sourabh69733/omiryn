"""Verifies atomic and idempotent persistence of validated memory operations."""

from __future__ import annotations

import unittest

import storage


class MemoryApplicationsTest(unittest.TestCase):
    def setUp(self) -> None:
        storage.reset_db()
        self.user_id = "memory-application-user"
        self.conversation_id = "memory-application-conversation"
        storage.save_conversation(
            {
                "id": self.conversation_id,
                "status": "active",
                "messages": [{"role": "user", "content": "I prefer calm, funny people."}],
            },
            self.user_id,
        )

    def test_add_is_persisted_with_audit_and_is_idempotent(self) -> None:
        payload = self._batch(self._add_operation())

        first = self._apply(payload)
        repeated = self._apply(payload)

        facts = storage.list_profile_facts(self.user_id)
        audit = self._list_applications()
        self.assertEqual(first["applied_count"], 1)
        self.assertFalse(first["idempotent"])
        self.assertTrue(repeated["idempotent"])
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["label"], "Prefers calm and funny partners")
        self.assertEqual(facts[0]["evidence"][0]["message_index"], 0)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["outcome"], "applied")
        self.assertIsNone(audit[0]["before"])
        self.assertEqual(audit[0]["after"]["id"], facts[0]["id"])

    def test_reinforce_adds_evidence_without_rewriting_meaning(self) -> None:
        existing = storage.upsert_profile_fact(
            {
                "user_id": self.user_id,
                "category": "partner_preferences",
                "key": "preferred_personality",
                "label": "Prefers calm partners",
                "value": {"traits": ["calm"]},
                "confidence": 0.6,
                "fact_type": "matching_fact",
                "source_kind": "agent_chat",
                "source_id": self.conversation_id,
                "evidence": [{"message_index": 0, "text": "I prefer calm people."}],
                "status": "active",
                "visibility": "internal",
                "used_for_matching": True,
                "used_for_chat_context": True,
            }
        )
        operation = {
            "operation_index": 0,
            "operation_fingerprint": "reinforce-fingerprint",
            "operation": "reinforce",
            "target_memory_id": existing["id"],
            "data_point_type": "profile_fact",
            "category": "wrong-category",
            "key": "wrong-key",
            "label": "Wrong replacement label",
            "value": {"wrong": True},
            "confidence": 0.9,
            "evidence": [
                {
                    "conversation_id": self.conversation_id,
                    "message_index": 2,
                    "text": "Calm people make me feel comfortable.",
                }
            ],
        }

        result = self._apply(self._batch(operation))

        stored = storage.get_profile_fact(existing["id"], self.user_id)
        assert stored is not None
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(stored["category"], existing["category"])
        self.assertEqual(stored["key"], existing["key"])
        self.assertEqual(stored["label"], existing["label"])
        self.assertEqual(stored["value"], existing["value"])
        self.assertEqual(stored["confidence"], 0.9)
        self.assertEqual([item["message_index"] for item in stored["evidence"]], [0, 2])

    def test_supersede_and_retract_are_recorded_without_mutating_fact(self) -> None:
        existing = self._existing_fact()
        before = storage.get_profile_fact(existing["id"], self.user_id)
        operations = [
            {
                "operation_index": 0,
                "operation_fingerprint": "supersede-fingerprint",
                "operation": "supersede",
                "target_memory_id": existing["id"],
                "data_point_type": "matching_fact",
                "category": "location",
                "key": "preferred_city",
                "label": "Location is flexible",
                "value": {"preference": "flexible"},
                "confidence": 0.9,
                "evidence": self._evidence(),
            },
            {
                "operation_index": 1,
                "operation_fingerprint": "retract-fingerprint",
                "operation": "retract",
                "target_memory_id": existing["id"],
                "evidence": self._evidence(),
            },
        ]

        result = self._apply(self._batch(*operations))

        after = storage.get_profile_fact(existing["id"], self.user_id)
        audit = self._list_applications()
        self.assertEqual(result["applied_count"], 0)
        self.assertEqual(result["deferred_count"], 2)
        self.assertEqual(after, before)
        self.assertEqual([row["outcome"] for row in audit], ["deferred", "deferred"])

    def test_invalid_target_rolls_back_the_complete_batch(self) -> None:
        invalid_reinforcement = {
            "operation_index": 1,
            "operation_fingerprint": "missing-target-fingerprint",
            "operation": "reinforce",
            "target_memory_id": "missing-fact",
            "confidence": 0.8,
            "evidence": self._evidence(),
        }

        with self.assertRaisesRegex(ValueError, "active memory target"):
            self._apply(self._batch(self._add_operation(), invalid_reinforcement))

        self.assertEqual(storage.list_profile_facts(self.user_id), [])
        self.assertEqual(self._list_applications(), [])

    def test_target_from_another_user_is_rejected(self) -> None:
        other = storage.upsert_profile_fact(
            {
                **self._fact_payload(),
                "user_id": "another-user",
            }
        )
        operation = {
            "operation_index": 0,
            "operation_fingerprint": "cross-user-fingerprint",
            "operation": "reinforce",
            "target_memory_id": other["id"],
            "confidence": 0.8,
            "evidence": self._evidence(),
        }

        with self.assertRaisesRegex(ValueError, "active memory target"):
            self._apply(self._batch(operation))

        self.assertEqual(self._list_applications(), [])

    def test_conversation_deletion_removes_operation_audit(self) -> None:
        self._apply(self._batch(self._add_operation()))
        self.assertEqual(len(self._list_applications()), 1)

        self.assertTrue(storage.delete_conversation(self.conversation_id, self.user_id))

        self.assertEqual(self._list_applications(), [])

    def test_user_deletion_removes_operation_audit(self) -> None:
        self._apply(self._batch(self._add_operation()))
        self.assertEqual(len(self._list_applications()), 1)

        storage.delete_user_private_data(self.user_id)

        self.assertEqual(self._list_applications(), [])

    def _apply(self, payload: dict[str, object]) -> dict[str, object]:
        function = getattr(storage, "apply_memory_operation_batch", None)
        self.assertTrue(callable(function), "storage.apply_memory_operation_batch is missing")
        return function(payload)

    def _list_applications(self) -> list[dict[str, object]]:
        function = getattr(storage, "list_memory_operation_applications", None)
        self.assertTrue(
            callable(function),
            "storage.list_memory_operation_applications is missing",
        )
        return function(self.user_id, self.conversation_id)

    def _batch(self, *operations: dict[str, object]) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "batch_key": "stable-batch-key",
            "operations": list(operations),
        }

    def _add_operation(self) -> dict[str, object]:
        return {
            "operation_index": 0,
            "operation_fingerprint": "add-fingerprint",
            "operation": "add",
            "target_memory_id": None,
            "data_point_type": "matching_fact",
            "category": "partner_preferences",
            "key": "preferred_personality",
            "label": "Prefers calm and funny partners",
            "value": {"traits": ["calm", "funny"]},
            "confidence": 0.9,
            "evidence": self._evidence(),
        }

    def _existing_fact(self) -> dict[str, object]:
        return storage.upsert_profile_fact(self._fact_payload())

    def _fact_payload(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "category": "location",
            "key": "preferred_city",
            "label": "Prefers Bengaluru",
            "value": {"city": "Bengaluru"},
            "confidence": 0.8,
            "fact_type": "matching_fact",
            "source_kind": "agent_chat",
            "source_id": self.conversation_id,
            "evidence": self._evidence(),
            "status": "active",
            "visibility": "internal",
            "used_for_matching": True,
            "used_for_chat_context": True,
        }

    def _evidence(self) -> list[dict[str, object]]:
        return [
            {
                "conversation_id": self.conversation_id,
                "message_index": 0,
                "text": "I prefer calm, funny people.",
            }
        ]


if __name__ == "__main__":
    unittest.main()
