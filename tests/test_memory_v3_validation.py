"""Verifies the general v3 memory contract without semantic keyword rules."""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

from agent.memory_engine.memories.validation import validate_memory_analysis_v3
from agent.memory_engine.processing import build_memory_batch
from agent.providers.extraction.service import analyze_background_cognition


class MemoryV3ValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.batch = build_memory_batch(
            conversation_id="conversation-v3",
            user_id="user-v3",
            messages=[
                {"role": "user", "content": "I spoke with Riya yesterday."},
                {"role": "assistant", "content": "How did that feel?"},
            ],
        )
        assert self.batch is not None

    def test_all_memory_kinds_use_the_same_general_contract(self) -> None:
        for kind in ("semantic", "episodic", "relationship", "procedural"):
            with self.subTest(kind=kind):
                result = validate_memory_analysis_v3(
                    self._analysis(memory_kind=kind),
                    batch=self.batch,
                )
                self.assertTrue(result.valid, result.errors)
                self.assertEqual(result.operations[0].kind.value, kind)

    def test_rejects_assistant_or_unknown_evidence_indexes(self) -> None:
        for index in (1, 99):
            with self.subTest(index=index):
                result = validate_memory_analysis_v3(
                    self._analysis(evidence_message_indexes=[index]),
                    batch=self.batch,
                )
                # The memory citing a companion message (or none) is dropped, not saved.
                self.assertEqual(result.operations, ())
                self.assertIn("ineligible message indexes", " ".join(result.dropped))

    def test_one_bad_operation_keeps_the_good_ones(self) -> None:
        good = self._analysis()["operations"][0]
        bad = {**good, "evidence_message_indexes": [99]}
        result = validate_memory_analysis_v3(
            {**self._analysis(), "operations": [bad, good]},
            batch=self.batch,
        )

        self.assertTrue(result.valid)
        self.assertEqual(len(result.operations), 1)
        self.assertEqual(result.decision, "propose")
        self.assertIn("operations[0]", " ".join(result.dropped))

    def test_a_bad_handoff_keeps_the_previous_one_and_the_memories(self) -> None:
        result = validate_memory_analysis_v3(
            {**self._analysis(), "handoff": "not an object"},
            batch=self.batch,
        )

        self.assertTrue(result.valid)
        self.assertEqual(len(result.operations), 1)
        self.assertEqual(result.handoff, self.batch.previous_handoff)
        self.assertIn("handoff", " ".join(result.dropped))

    def test_only_a_malformed_response_is_invalid(self) -> None:
        for raw in ("text", {"operations": "nope"}):
            with self.subTest(raw=raw):
                self.assertFalse(validate_memory_analysis_v3(raw, batch=self.batch).valid)

    def test_rejects_unknown_taxonomy_and_duplicate_purposes(self) -> None:
        result = validate_memory_analysis_v3(
            self._analysis(
                memory_kind="working",
                purposes=["profile", "profile"],
            ),
            batch=self.batch,
        )

        self.assertTrue(result.valid)
        self.assertEqual(result.operations, ())
        self.assertIn("memory_kind", " ".join(result.dropped))
        self.assertIn("duplicates", " ".join(result.dropped))

    def test_keeps_a_plain_statement(self) -> None:
        result = validate_memory_analysis_v3(
            self._analysis(statement="  Spoke with   Riya. "), batch=self.batch
        )
        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.operations[0].statement, "Spoke with Riya.")

    def test_bad_statement_is_dropped_but_the_memory_is_kept(self) -> None:
        for statement in (42, "", "x" * 241):
            with self.subTest(statement=statement):
                result = validate_memory_analysis_v3(
                    self._analysis(statement=statement), batch=self.batch
                )
                self.assertTrue(result.valid, result.errors)
                self.assertIsNone(result.operations[0].statement)

    def _analysis(self, **changes: object) -> dict[str, object]:
        operation: dict[str, object] = {
            "operation": "add",
            "memory_kind": "episodic",
            "purposes": ["personalization"],
            "key": "relationships.riya.conversation",
            "value": {"event": "spoke", "person": "Riya"},
            "sensitivity": "standard",
            "confidence": 0.9,
            "importance": 0.6,
            "occurred_at": None,
            "valid_from": None,
            "valid_until": None,
            "evidence_message_indexes": [0],
        }
        operation.update(changes)
        return {
            "decision": "propose",
            "operations": [operation],
            "handoff": {
                "summary": "Riya is an active person.",
                "active_people": ["Riya"],
                "active_topics": [],
                "unresolved_references": [],
            },
        }


class MemoryV3ProviderPromptTest(unittest.IsolatedAsyncioTestCase):
    async def test_v3_selects_v3_prompt_in_the_existing_single_call(self) -> None:
        raw = {
            "decision": "no_change",
            "operations": [],
            "thread_operation": {"operation": "none"},
            "handoff": {
                "summary": "",
                "active_people": [],
                "active_topics": [],
                "unresolved_references": [],
            },
        }
        with (
            patch(
                "agent.providers.extraction.service._provider_name",
                return_value="deepinfra",
            ),
            patch(
                "agent.providers.extraction.service.provider_chat",
                new_callable=AsyncMock,
                return_value=json.dumps(raw),
            ) as provider,
        ):
            result = await analyze_background_cognition(
                "{}",
                conversation_id="conversation-v3",
                memory_version=3,
            )

        self.assertEqual(result, raw)
        system_prompt = provider.await_args.kwargs["system_prompt"]
        self.assertIn('"memory_kind"', system_prompt)
        self.assertNotIn('"data_point_type"', system_prompt)
        self.assertIn("matching is only for finding friends", system_prompt.lower())
        self.assertIn("dating preferences", system_prompt.lower())
        self.assertEqual(provider.await_args.kwargs["request_kind"], "background_cognition")
        self.assertEqual(provider.await_count, 1)


if __name__ == "__main__":
    unittest.main()
