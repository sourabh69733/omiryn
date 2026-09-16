"""Regression tests for pipeline-derived conversation data-point capture."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from agent.config import agent_pipeline_config
from agent.context_engine.engine import build_model_context_package
from agent.memory_engine.data_points.extraction.registry import data_point_capture_policy
from agent.memory_engine.engine import (
    capture_profile_facts_from_user_message,
    should_run_conversation_data_point_extraction,
)
from storage import list_agent_behavior_rules, reset_db


class DataPointCapturePolicyTest(unittest.TestCase):
    def test_default_v2_shadow_disables_inline_capture(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            policy = data_point_capture_policy()

        self.assertEqual(policy.strategy, "disabled")
        self.assertFalse(policy.inline)
        self.assertFalse(policy.immediate_rules)
        self.assertIsNone(policy.background_mode)

    def test_v1_is_the_single_legacy_rules_mode(self) -> None:
        with patch.dict(
            os.environ,
            {"AGENT_PIPELINE_VERSION": "v1", "AGENT_ROLLOUT": "off"},
            clear=True,
        ):
            policy = data_point_capture_policy()

        self.assertEqual(policy.strategy, "legacy_rules")
        self.assertFalse(policy.inline)
        self.assertTrue(policy.immediate_rules)
        self.assertIsNone(policy.background_mode)

    def test_live_mode_disables_inline_capture_for_background_memory(self) -> None:
        with patch.dict(
            os.environ,
            {"AGENT_PIPELINE_VERSION": "v2", "AGENT_ROLLOUT": "live"},
            clear=True,
        ):
            policy = data_point_capture_policy()

        self.assertEqual(policy.strategy, "disabled")
        self.assertFalse(policy.inline)
        self.assertFalse(policy.immediate_rules)
        self.assertIsNone(policy.background_mode)
        self.assertFalse(agent_pipeline_config().structured_turn_output)

    def test_removed_flags_cannot_override_the_central_pipeline(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AGENT_PIPELINE_VERSION": "v2",
                "AGENT_ROLLOUT": "live",
                "AGENT_TURN_OUTPUT_VERSION": "v1",
                "DATA_POINT_CAPTURE_STRATEGY": "legacy_rules",
            },
            clear=True,
        ):
            self.assertFalse(agent_pipeline_config().structured_turn_output)
            self.assertEqual(data_point_capture_policy().strategy, "disabled")

    def test_v2_skips_legacy_fact_rules_but_keeps_behavior_learning(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"AGENT_PIPELINE_VERSION": "v2", "AGENT_ROLLOUT": "shadow"},
                clear=True,
            ),
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

    def test_v3_skips_legacy_fact_and_behavior_rules(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"AGENT_PIPELINE_VERSION": "v3"},
                clear=True,
            ),
            patch("agent.memory_engine.engine.extract_profile_facts_from_message") as facts,
            patch(
                "agent.memory_engine.engine.extract_agent_behavior_rules_from_message",
                return_value=[],
            ) as behavior,
            patch("agent.memory_engine.engine.upsert_profile_fact") as save_fact,
            patch("agent.memory_engine.engine.upsert_agent_behavior_rule") as save_behavior,
        ):
            capture_profile_facts_from_user_message("c", "u", "remember this", 1, True)

        facts.assert_not_called()
        behavior.assert_not_called()
        save_fact.assert_not_called()
        save_behavior.assert_not_called()

    def test_v3_does_not_use_preexisting_legacy_behavior_rules(self) -> None:
        reset_db()
        with patch.dict(
            os.environ,
            {"AGENT_PIPELINE_VERSION": "v2", "AGENT_ROLLOUT": "live"},
            clear=True,
        ):
            capture_profile_facts_from_user_message(
                "conversation-a",
                "user-a",
                "first of all, u r not sunata hoon, you are sunati hoon.",
                2,
                True,
            )
        self.assertEqual(len(list_agent_behavior_rules("user-a")), 1)

        with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3"}, clear=True):
            package = build_model_context_package(
                conversation_id="conversation-a",
                user_text="haan ab ek funny story sunao",
                user_id="user-a",
                user_profile={"user_id": "user-a", "interested_in": "women"},
                model="llama-70b",
                agent_tone="auto",
                agent_name="Annie",
                style_source_id=None,
                user_message_index=3,
                assistant_message_index=4,
                prompt_version_id="v3",
            )

        self.assertNotIn("User-taught behavior rules", package.system_prompt)
        self.assertFalse(package.snapshot["summary"]["used_agent_behavior_rules"])

    def test_old_interval_extractor_is_not_scheduled_by_the_main_pipeline(self) -> None:
        messages = [{"role": "user", "content": "A useful durable preference."}]
        modes = (("v1", "off"), ("v2", "off"), ("v2", "shadow"), ("v2", "live"))
        for version, rollout in modes:
            with self.subTest(version=version, rollout=rollout), patch.dict(
                os.environ,
                {
                    "AGENT_PIPELINE_VERSION": version,
                    "AGENT_ROLLOUT": rollout,
                    "PROFILE_FACT_DEEP_EXTRACT_INTERVAL": "1",
                },
                clear=True,
            ):
                self.assertFalse(
                    should_run_conversation_data_point_extraction("c", "u", messages, True)
                )


if __name__ == "__main__":
    unittest.main()
