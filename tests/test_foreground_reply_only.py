"""Protects the foreground companion call from background cognition work."""

from __future__ import annotations

import unittest

import agent.runtime.orchestrator as orchestrator
from unittest.mock import AsyncMock, patch

from agent.context_engine.contracts.models import ModelContextPackage
from agent.runtime.orchestrator import run_agent_turn


class ForegroundReplyOnlyTest(unittest.IsolatedAsyncioTestCase):
    async def test_v2_foreground_requests_and_returns_only_plain_reply_text(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {"AGENT_PIPELINE_VERSION": "v2", "AGENT_ROLLOUT": "live"},
            ),
            patch("agent.runtime.orchestrator.capture_profile_facts_from_user_message"),
            patch("agent.runtime.orchestrator.build_model_context_package") as context,
            patch(
                "agent.runtime.orchestrator.generate_agent_reply",
                new_callable=AsyncMock,
                return_value="That sounds like a meaningful change. What led to it?",
            ) as provider,
            patch("agent.runtime.orchestrator.save_agent_context_snapshot"),
            patch("agent.runtime.orchestrator.save_agent_trace") as save_trace,
            patch("agent.runtime.orchestrator.save_agent_trace_step"),
            patch("agent.runtime.orchestrator.finish_agent_trace"),
        ):
            save_trace.return_value = {"id": "trace-reply-only"}
            context.return_value = ModelContextPackage(
                system_prompt="system prompt",
                context_sources=[],
                snapshot={
                    "conversation_id": "conversation-a",
                    "message_index": 1,
                    "summary": {"included_source_count": 0, "rough_context_tokens": 0},
                },
            )

            result = await run_agent_turn(
                conversation_id="conversation-a",
                messages=[],
                user_text="I am thinking about changing careers.",
                user_id="user-a",
                user_profile=None,
                model="llama-70b",
                agent_mode="know_me",
                agent_tone="auto",
                style_source_id=None,
            )

        self.assertEqual(
            result.messages[-1]["content"],
            "That sounds like a meaningful change. What led to it?",
        )
        self.assertIsNone(provider.await_args.kwargs.get("tools"))
        self.assertIsNone(provider.await_args.kwargs.get("tool_choice"))
        self.assertFalse(hasattr(orchestrator, "parse_turn_output_v2"))
        self.assertFalse(hasattr(orchestrator, "capture_turn_output_data_points"))


if __name__ == "__main__":
    unittest.main()
