"""Verifies shadow extraction without allowing model proposals to mutate memory."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from agent.memory_engine.processing import MemoryHandoff, MemoryProcessingState, build_memory_batch
from agent.memory_engine.processing.shadow import (
    run_shadow_memory_extraction,
    should_schedule_shadow_memory_extraction,
    validate_shadow_memory_analysis,
)
from storage import (
    list_data_point_extraction_debug,
    list_profile_facts,
    reset_db,
    save_conversation,
)
from agent.memory_engine.processing import get_processing_state, save_processing_state


class MemoryShadowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.user_id = "shadow-user"
        self.conversation_id = "shadow-conversation"
        self.messages = [
            {"role": "user", "content": "My friend Priya moved to Chennai."},
            {"role": "assistant", "content": "That is a big change."},
            {"role": "user", "content": "She is calm and very funny."},
            {"role": "assistant", "content": "That combination matters to you."},
        ]
        save_conversation(
            {
                "id": self.conversation_id,
                "status": "active",
                "messages": self.messages,
            },
            self.user_id,
        )

    def test_scheduler_is_flagged_and_uses_meaningful_threshold(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "MEMORY_BACKGROUND_V2_SHADOW": "true",
                "MEMORY_BACKGROUND_V2_THRESHOLD": "2",
            },
        ):
            self.assertTrue(
                should_schedule_shadow_memory_extraction(
                    self.conversation_id,
                    self.user_id,
                    self.messages,
                    True,
                )
            )
        with patch.dict("os.environ", {"MEMORY_BACKGROUND_V2_SHADOW": "false"}):
            self.assertFalse(
                should_schedule_shadow_memory_extraction(
                    self.conversation_id,
                    self.user_id,
                    self.messages,
                    True,
                )
            )

    def test_validator_accepts_user_evidence_and_rejects_context_or_assistant_evidence(self) -> None:
        state = MemoryProcessingState(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            processed_through_message_index=1,
            handoff=MemoryHandoff(active_people=("Priya",)),
        )
        batch = build_memory_batch(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            messages=self.messages,
            state=state,
        )
        assert batch is not None
        valid = validate_shadow_memory_analysis(
            self._analysis(evidence_indexes=[2]),
            batch=batch,
            existing_memory_ids=set(),
        )
        self.assertTrue(valid.valid)
        self.assertEqual(valid.operations[0].evidence_message_indexes, (2,))

        for invalid_index in (0, 3):
            with self.subTest(invalid_index=invalid_index):
                invalid = validate_shadow_memory_analysis(
                    self._analysis(evidence_indexes=[invalid_index]),
                    batch=batch,
                    existing_memory_ids=set(),
                )
                self.assertFalse(invalid.valid)
                self.assertIn("ineligible message indexes", " ".join(invalid.errors))

    def test_validator_rejects_unknown_target_and_entire_mixed_result(self) -> None:
        batch = build_memory_batch(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            messages=self.messages,
        )
        assert batch is not None
        raw = self._analysis(evidence_indexes=[0])
        raw["operations"].append(
            {
                "operation": "retract",
                "target_memory_id": "invented-memory",
                "evidence_message_indexes": [2],
            }
        )
        result = validate_shadow_memory_analysis(
            raw,
            batch=batch,
            existing_memory_ids={"real-memory"},
        )
        self.assertFalse(result.valid)
        self.assertEqual(result.operations, ())
        self.assertIn("supplied existing target_memory_id", " ".join(result.errors))

    async def test_worker_records_valid_shadow_result_without_live_memory_write(self) -> None:
        with (
            patch.dict("os.environ", {"MEMORY_BACKGROUND_V2_THRESHOLD": "2"}),
            patch(
                "agent.memory_engine.processing.shadow.analyze_memory_batch",
                new_callable=AsyncMock,
                return_value=self._analysis(evidence_indexes=[0, 2]),
            ) as analyze,
        ):
            result = await run_shadow_memory_extraction(
                self.conversation_id,
                self.user_id,
                self.messages,
                "memory-model",
            )
            repeated = await run_shadow_memory_extraction(
                self.conversation_id,
                self.user_id,
                self.messages,
                "memory-model",
            )

        self.assertEqual(result["status"], "shadow_valid")
        self.assertEqual(result["operation_count"], 1)
        self.assertEqual(repeated["status"], "no_pending_messages")
        self.assertEqual(analyze.await_count, 1)
        self.assertEqual(list_profile_facts(self.user_id), [])

        state = get_processing_state(self.conversation_id, self.user_id)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.processed_through_message_index, 3)
        self.assertEqual(state.handoff.active_people, ("Priya",))

        debug = list_data_point_extraction_debug(
            user_id=self.user_id,
            source_id=self.conversation_id,
        )
        self.assertEqual(len(debug), 1)
        self.assertEqual(debug[0]["decision"], "shadow_valid")
        self.assertFalse(debug[0]["review"]["live_writes"])

    async def test_invalid_result_advances_cursor_but_preserves_previous_handoff(self) -> None:
        initial = save_processing_state(
            MemoryProcessingState(
                conversation_id=self.conversation_id,
                user_id=self.user_id,
                processed_through_message_index=1,
                last_batch_key="old-batch",
                handoff=MemoryHandoff(
                    summary="Priya was introduced earlier.",
                    active_people=("Priya",),
                ),
            )
        )
        invalid = self._analysis(evidence_indexes=[3])
        with patch(
            "agent.memory_engine.processing.shadow.analyze_memory_batch",
            new_callable=AsyncMock,
            return_value=invalid,
        ):
            result = await run_shadow_memory_extraction(
                self.conversation_id,
                self.user_id,
                self.messages,
            )

        self.assertEqual(result["status"], "shadow_invalid")
        state = get_processing_state(self.conversation_id, self.user_id)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertGreater(state.version, initial.version)
        self.assertEqual(state.handoff, initial.handoff)
        self.assertEqual(list_profile_facts(self.user_id), [])

    async def test_provider_error_is_observed_without_advancing_cursor(self) -> None:
        with patch(
            "agent.memory_engine.processing.shadow.analyze_memory_batch",
            new_callable=AsyncMock,
            side_effect=TimeoutError("provider timed out"),
        ):
            result = await run_shadow_memory_extraction(
                self.conversation_id,
                self.user_id,
                self.messages,
            )

        self.assertEqual(result["status"], "shadow_error")
        self.assertIsNone(get_processing_state(self.conversation_id, self.user_id))
        self.assertEqual(list_profile_facts(self.user_id), [])
        debug = list_data_point_extraction_debug(
            user_id=self.user_id,
            source_id=self.conversation_id,
        )
        self.assertEqual(debug[0]["decision"], "shadow_error")

    @staticmethod
    def _analysis(*, evidence_indexes: list[int]) -> dict[str, object]:
        return {
            "decision": "propose",
            "operations": [
                {
                    "operation": "add",
                    "target_memory_id": None,
                    "data_point_type": "matching_fact",
                    "category": "partner_preferences",
                    "key": "preferred_personality",
                    "label": "Prefers calm and funny partners",
                    "value": ["calm", "funny"],
                    "confidence": 0.9,
                    "evidence_message_indexes": evidence_indexes,
                }
            ],
            "handoff": {
                "summary": "Priya is being discussed as an example of preferred personality.",
                "active_people": ["Priya"],
                "active_topics": ["partner personality"],
                "unresolved_references": [],
            },
        }


if __name__ == "__main__":
    unittest.main()
