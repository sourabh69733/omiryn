"""Verifies mapping from validated memory analysis to safe storage operations."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import agent.memory_engine.processing as processing
from agent.memory_engine.processing.models import MemoryHandoff, MemoryProcessingState
from agent.memory_engine.processing.shadow import ShadowMemoryAnalysis
from storage import (
    list_memory_operation_applications,
    list_profile_facts,
    reset_db,
    save_conversation,
)


class MemoryApplicationServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        self.user_id = "memory-service-user"
        self.conversation_id = "memory-service-conversation"
        self.messages = [
            {"role": "user", "content": "My friend Asha introduced me to chess."},
            {"role": "assistant", "content": "That sounds memorable."},
            {"role": "user", "content": "I now really enjoy long chess games."},
        ]
        save_conversation(
            {
                "id": self.conversation_id,
                "status": "active",
                "messages": self.messages,
            },
            self.user_id,
        )

    def test_live_writes_follow_pipeline_rollout(self) -> None:
        function = self._function("memory_background_v2_live_writes_enabled")
        with patch.dict(
            os.environ,
            {"AGENT_PIPELINE_VERSION": "v2", "AGENT_ROLLOUT": "shadow"},
            clear=True,
        ):
            self.assertFalse(function())
        with patch.dict(
            os.environ,
            {"AGENT_PIPELINE_VERSION": "v2", "AGENT_ROLLOUT": "live"},
            clear=True,
        ):
            self.assertTrue(function())

    def test_valid_analysis_resolves_exact_eligible_user_evidence(self) -> None:
        batch = self._batch()
        analysis = ShadowMemoryAnalysis(
            decision="propose",
            operations=(
                processing.MemoryOperation(
                    operation="add",
                    data_point_type="matching_fact",
                    category="hobbies",
                    key="favorite_game",
                    label="Enjoys long chess games",
                    value={"game": "chess", "style": "long games"},
                    confidence=0.9,
                    evidence_message_indexes=(2,),
                ),
            ),
            handoff=MemoryHandoff(active_topics=("chess",)),
            valid=True,
        )

        result = self._apply(batch, analysis)
        repeated = self._apply(batch, analysis)

        facts = list_profile_facts(self.user_id)
        audit = list_memory_operation_applications(self.user_id, self.conversation_id)
        self.assertEqual(result.applied_count, 1)
        self.assertFalse(result.idempotent)
        self.assertTrue(repeated.idempotent)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["category"], "hobbies")
        self.assertEqual(facts[0]["key"], "favorite_game")
        self.assertEqual(
            facts[0]["evidence"],
            [
                {
                    "conversation_id": self.conversation_id,
                    "message_index": 2,
                    "text": self.messages[2]["content"],
                    "quote": self.messages[2]["content"],
                }
            ],
        )
        self.assertEqual(len(audit[0]["operation_fingerprint"]), 64)

    def test_invalid_analysis_is_rejected_before_storage(self) -> None:
        batch = self._batch()
        analysis = ShadowMemoryAnalysis(
            decision="invalid",
            operations=(),
            handoff=batch.previous_handoff,
            valid=False,
            errors=("invalid evidence",),
        )

        with self.assertRaisesRegex(ValueError, "validated memory analysis"):
            self._apply(batch, analysis)

        self.assertEqual(list_profile_facts(self.user_id), [])
        self.assertEqual(
            list_memory_operation_applications(self.user_id, self.conversation_id),
            [],
        )

    def test_missing_eligible_evidence_is_rejected_before_storage(self) -> None:
        batch = self._batch()
        analysis = ShadowMemoryAnalysis(
            decision="propose",
            operations=(
                processing.MemoryOperation(
                    operation="add",
                    data_point_type="matching_fact",
                    category="hobbies",
                    key="favorite_game",
                    label="Enjoys chess",
                    value={"game": "chess"},
                    confidence=0.8,
                    evidence_message_indexes=(0,),
                ),
            ),
            handoff=MemoryHandoff(),
            valid=True,
        )

        with self.assertRaisesRegex(ValueError, "eligible user evidence"):
            self._apply(batch, analysis)

        self.assertEqual(list_profile_facts(self.user_id), [])

    def _batch(self):
        batch = processing.build_memory_batch(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            messages=self.messages,
            state=MemoryProcessingState(
                conversation_id=self.conversation_id,
                user_id=self.user_id,
                processed_through_message_index=1,
            ),
        )
        assert batch is not None
        return batch

    def _apply(self, batch, analysis):
        return self._function("apply_validated_memory_analysis")(batch, analysis)

    def _function(self, name: str):
        function = getattr(processing, name, None)
        self.assertTrue(callable(function), f"processing.{name} is missing")
        return function


if __name__ == "__main__":
    unittest.main()
