"""Regression tests for exclusive conversation data-point capture strategies."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from agent.memory_engine.data_points.extraction.inline.config import turn_output_v2_enabled
from agent.memory_engine.data_points.extraction.registry import data_point_capture_policy
from agent.memory_engine.engine import (
    capture_profile_facts_from_user_message,
    should_run_conversation_data_point_extraction,
)


class DataPointCapturePolicyTest(unittest.TestCase):
    def test_default_v2_uses_only_inline_even_when_legacy_extractor_is_rules(self) -> None:
        with patch.dict(
            os.environ,
            {"AGENT_TURN_OUTPUT_VERSION": "v2", "DATA_POINT_EXTRACTOR": "rules"},
        ):
            os.environ.pop("DATA_POINT_CAPTURE_STRATEGY", None)
            policy = data_point_capture_policy()

        self.assertEqual(policy.strategy, "inline_llm")
        self.assertTrue(policy.inline)
        self.assertFalse(policy.immediate_rules)
        self.assertIsNone(policy.background_mode)

    def test_explicit_strategies_are_mutually_exclusive(self) -> None:
        expected = {
            "inline_llm": (True, False, None),
            "legacy_rules": (False, True, None),
            "background_llm": (False, False, "llm"),
            "hybrid_review": (False, False, "hybrid"),
            "disabled": (False, False, None),
        }
        for strategy, flags in expected.items():
            with self.subTest(strategy=strategy), patch.dict(
                os.environ,
                {"DATA_POINT_CAPTURE_STRATEGY": strategy},
            ):
                policy = data_point_capture_policy()
                self.assertEqual(
                    (policy.inline, policy.immediate_rules, policy.background_mode),
                    flags,
                )

    def test_v1_compatibility_maps_old_extractor_setting(self) -> None:
        with patch.dict(
            os.environ,
            {"AGENT_TURN_OUTPUT_VERSION": "v1", "DATA_POINT_EXTRACTOR": "hybrid"},
        ):
            os.environ.pop("DATA_POINT_CAPTURE_STRATEGY", None)
            policy = data_point_capture_policy()

        self.assertEqual(policy.strategy, "hybrid_review")
        self.assertEqual(policy.background_mode, "hybrid")

    def test_unknown_explicit_strategy_fails_configuration_early(self) -> None:
        with patch.dict(os.environ, {"DATA_POINT_CAPTURE_STRATEGY": "mystery"}):
            with self.assertRaisesRegex(ValueError, "Unknown DATA_POINT_CAPTURE_STRATEGY"):
                data_point_capture_policy()

    def test_inline_config_delegates_to_capture_policy(self) -> None:
        with patch.dict(os.environ, {"DATA_POINT_CAPTURE_STRATEGY": "inline_llm"}):
            self.assertTrue(turn_output_v2_enabled())
        with patch.dict(os.environ, {"DATA_POINT_CAPTURE_STRATEGY": "background_llm"}):
            self.assertFalse(turn_output_v2_enabled())

    def test_inline_strategy_skips_legacy_fact_rules_but_keeps_behavior_learning(self) -> None:
        with (
            patch.dict(os.environ, {"DATA_POINT_CAPTURE_STRATEGY": "inline_llm"}),
            patch("agent.memory_engine.engine.extract_profile_facts_from_message") as facts,
            patch(
                "agent.memory_engine.engine.extract_agent_behavior_rules_from_message",
                return_value=[],
            ) as behavior,
            patch("agent.memory_engine.engine.upsert_profile_fact") as save_fact,
        ):
            capture_profile_facts_from_user_message("c", "u", "remember this", 1, True)

        facts.assert_not_called()
        save_fact.assert_not_called()
        behavior.assert_called_once()

    def test_only_background_strategies_schedule_interval_extraction(self) -> None:
        messages = [{"role": "user", "content": "A useful durable preference."}]
        for strategy, expected in (
            ("inline_llm", False),
            ("legacy_rules", False),
            ("disabled", False),
            ("background_llm", True),
            ("hybrid_review", True),
        ):
            with self.subTest(strategy=strategy), patch.dict(
                os.environ,
                {
                    "DATA_POINT_CAPTURE_STRATEGY": strategy,
                    "PROFILE_FACT_DEEP_EXTRACT_INTERVAL": "1",
                },
            ):
                self.assertEqual(
                    should_run_conversation_data_point_extraction("c", "u", messages, True),
                    expected,
                )


if __name__ == "__main__":
    unittest.main()
