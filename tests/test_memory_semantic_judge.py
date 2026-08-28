"""Tests evidence-grounded semantic judging of proposed memories."""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

from agent.evals.memory.judge import (
    ProviderMemoryEvidenceJudge,
    build_memory_evidence_judge_request,
    parse_memory_evidence_judgment,
)


class MemorySemanticJudgeTest(unittest.TestCase):
    def test_request_contains_only_cited_user_evidence_and_complete_operations(self) -> None:
        messages = (
            {"role": "user", "content": "I build a matchmaking product called Omiryn."},
            {"role": "assistant", "content": "That makes you a professional matchmaker."},
        )
        operations = (
            {
                "operation": "add",
                "data_point_type": "profile_fact",
                "memory_basis": "stable_user_attribute",
                "category": "work",
                "key": "job_title",
                "label": "Job title",
                "value": "Matchmaker",
                "evidence_message_indexes": [0],
            },
        )

        _system_prompt, payload_text = build_memory_evidence_judge_request(
            messages=messages,
            operations=operations,
        )
        payload = json.loads(payload_text)

        self.assertEqual(
            payload["evidence_messages"],
            [{"message_index": 0, "content": messages[0]["content"]}],
        )
        self.assertEqual(payload["operations"], list(operations))
        self.assertNotIn("professional matchmaker", payload_text)

    def test_parser_rejects_over_inferred_memory(self) -> None:
        judgment = parse_memory_evidence_judgment(
            json.dumps(
                {
                    "operations": [
                        {
                            "index": 0,
                            "supported": False,
                            "issues": ["unsupported_inference"],
                            "reason": "The user said they build a product, not that Matchmaker is their job title.",
                        }
                    ],
                    "overall_reason": "The proposed title goes beyond the evidence.",
                }
            ),
            operation_count=1,
        )

        self.assertFalse(judgment.passed)
        self.assertEqual(judgment.operations[0].issues, ("unsupported_inference",))

    def test_parser_requires_one_verdict_for_every_operation(self) -> None:
        raw = json.dumps(
            {
                "operations": [
                    {"index": 0, "supported": True, "issues": [], "reason": "Supported."}
                ],
                "overall_reason": "Only one operation was reviewed.",
            }
        )

        with self.assertRaisesRegex(ValueError, "every proposed operation"):
            parse_memory_evidence_judgment(raw, operation_count=2)


class ProviderMemorySemanticJudgeTest(unittest.IsolatedAsyncioTestCase):
    async def test_provider_judge_uses_independent_request_kind_and_json_mode(self) -> None:
        raw = json.dumps(
            {
                "operations": [
                    {
                        "index": 0,
                        "supported": True,
                        "issues": [],
                        "reason": "The user explicitly said they build Omiryn.",
                    }
                ],
                "overall_reason": "The memory is grounded.",
            }
        )
        judge = ProviderMemoryEvidenceJudge(
            provider="deepinfra",
            model="judge-model",
            timeout_seconds=30,
        )
        with patch(
            "agent.evals.memory.judge.provider_chat",
            new_callable=AsyncMock,
            return_value=raw,
        ) as provider_chat:
            judgment = await judge.judge_memories(
                messages=(
                    {"role": "user", "content": "I build Omiryn."},
                ),
                operations=(
                    {
                        "operation": "add",
                        "data_point_type": "profile_fact",
                        "memory_basis": "stable_user_attribute",
                        "label": "Builds Omiryn",
                        "value": "Omiryn",
                        "evidence_message_indexes": [0],
                    },
                ),
                conversation_id="memory-eval-conversation",
            )

        self.assertTrue(judgment.passed)
        kwargs = provider_chat.await_args.kwargs
        self.assertEqual(kwargs["request_kind"], "memory_eval_evidence_judge")
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})


if __name__ == "__main__":
    unittest.main()
