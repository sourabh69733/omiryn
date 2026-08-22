"""Verifies the single source of truth for agent runtime rollout behavior."""

from __future__ import annotations

import importlib
import os
import unittest
from unittest.mock import patch

from agent.config import agent_pipeline_config
from agent.context_engine.conversation_engine.state import (
    conversation_state_shadow_enabled,
    conversation_state_v2_enabled,
)
from agent.memory_engine.data_points.extraction.registry import data_point_capture_policy
from agent.memory_engine.processing import memory_background_v2_live_writes_enabled
from agent.cognition.background.service import background_cognition_enabled


class AgentPipelineConfigTest(unittest.TestCase):
    def test_default_is_v2_shadow_without_live_writes(self) -> None:
        config = self._config({})

        self.assertEqual(config.version, "v2")
        self.assertEqual(config.rollout, "shadow")
        self.assertFalse(config.structured_turn_output)
        self.assertFalse(config.inline_data_points)
        self.assertTrue(config.conversation_state_enabled)
        self.assertFalse(config.conversation_state_shadow)
        self.assertTrue(config.background_memory_enabled)
        self.assertFalse(config.live_memory_writes)
        self.assertFalse(config.live_thread_writes)
        self.assertFalse(config.legacy_rules)

    def test_v1_is_one_complete_legacy_rollback_mode(self) -> None:
        for rollout in ("off", "shadow", "live"):
            with self.subTest(rollout=rollout):
                config = self._config(
                    {
                        "AGENT_PIPELINE_VERSION": "v1",
                        "AGENT_ROLLOUT": rollout,
                    }
                )
                self.assertFalse(config.structured_turn_output)
                self.assertFalse(config.inline_data_points)
                self.assertFalse(config.conversation_state_enabled)
                self.assertFalse(config.conversation_state_shadow)
                self.assertFalse(config.background_memory_enabled)
                self.assertFalse(config.live_memory_writes)
                self.assertFalse(config.live_thread_writes)
                self.assertTrue(config.legacy_rules)

    def test_v2_off_keeps_reply_only_without_background_processing(self) -> None:
        config = self._config(
            {"AGENT_PIPELINE_VERSION": "v2", "AGENT_ROLLOUT": "off"}
        )

        self.assertFalse(config.structured_turn_output)
        self.assertFalse(config.inline_data_points)
        self.assertFalse(config.conversation_state_enabled)
        self.assertFalse(config.conversation_state_shadow)
        self.assertFalse(config.background_memory_enabled)
        self.assertFalse(config.live_memory_writes)
        self.assertFalse(config.live_thread_writes)

    def test_v2_live_uses_reply_only_foreground_and_background_memory(self) -> None:
        config = self._config(
            {"AGENT_PIPELINE_VERSION": "v2", "AGENT_ROLLOUT": "live"}
        )

        self.assertFalse(config.structured_turn_output)
        self.assertFalse(config.inline_data_points)
        self.assertTrue(config.conversation_state_enabled)
        self.assertFalse(config.conversation_state_shadow)
        self.assertTrue(config.background_memory_enabled)
        self.assertTrue(config.live_memory_writes)
        self.assertTrue(config.live_thread_writes)

    def test_unknown_version_or_rollout_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "AGENT_PIPELINE_VERSION"):
            self._config({"AGENT_PIPELINE_VERSION": "v3"})
        with self.assertRaisesRegex(ValueError, "AGENT_ROLLOUT"):
            self._config({"AGENT_ROLLOUT": "maybe"})

    def test_runtime_consumers_share_v1_rollback_decision(self) -> None:
        with patch.dict(
            os.environ,
            {"AGENT_PIPELINE_VERSION": "v1", "AGENT_ROLLOUT": "off"},
            clear=True,
        ):
            self.assertFalse(agent_pipeline_config().structured_turn_output)
            self.assertEqual(data_point_capture_policy().strategy, "legacy_rules")
            self.assertFalse(conversation_state_v2_enabled())
            self.assertFalse(conversation_state_shadow_enabled())
            self.assertFalse(background_cognition_enabled())
            self.assertFalse(memory_background_v2_live_writes_enabled())

    def test_runtime_consumers_share_live_decision_without_double_writer(self) -> None:
        with patch.dict(
            os.environ,
            {"AGENT_PIPELINE_VERSION": "v2", "AGENT_ROLLOUT": "live"},
            clear=True,
        ):
            self.assertFalse(agent_pipeline_config().structured_turn_output)
            self.assertEqual(data_point_capture_policy().strategy, "disabled")
            self.assertTrue(conversation_state_v2_enabled())
            self.assertFalse(conversation_state_shadow_enabled())
            self.assertTrue(background_cognition_enabled())
            self.assertTrue(memory_background_v2_live_writes_enabled())

    def _config(self, values: dict[str, str]):
        module = importlib.import_module("agent.config")
        function = getattr(module, "agent_pipeline_config", None)
        self.assertTrue(callable(function), "agent.config.agent_pipeline_config is missing")
        with patch.dict(os.environ, values, clear=True):
            return function()


if __name__ == "__main__":
    unittest.main()
