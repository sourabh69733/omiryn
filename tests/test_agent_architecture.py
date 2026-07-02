import unittest
from unittest.mock import AsyncMock, patch

from agent.context_engine.models import ContextQueryIntent, ModelContextPackage
from agent.runtime.orchestrator import run_agent_turn


class AgentArchitectureTest(unittest.IsolatedAsyncioTestCase):
    async def test_orchestrator_builds_context_before_calling_model(self) -> None:
        with (
            patch("agent.runtime.orchestrator.capture_profile_facts_from_user_message") as capture_facts,
            patch("agent.runtime.orchestrator.build_model_context_package") as build_context,
            patch("agent.runtime.orchestrator.generate_agent_reply", new_callable=AsyncMock) as model_call,
            patch("agent.runtime.orchestrator.save_agent_context_snapshot") as save_snapshot,
            patch("agent.runtime.orchestrator.save_agent_trace") as save_trace,
            patch("agent.runtime.orchestrator.save_agent_trace_step") as save_trace_step,
            patch("agent.runtime.orchestrator.finish_agent_trace") as finish_trace,
        ):
            save_trace.return_value = {"id": "trace-1"}
            build_context.return_value = ModelContextPackage(
                system_prompt="system prompt",
                user_profile={"user_id": "user-a", "interested_in": "women"},
                context_sources=[
                    {
                        "id": "source-1",
                        "source_type": "llm_profile",
                        "title": "Profile memory",
                        "content": "Career growth matters.",
                    }
                ],
                prompt_version="v1",
                prompt_version_name="v1_companion_basic",
                query_intent=ContextQueryIntent(("profile",), False),
                snapshot={
                    "conversation_id": "conversation-1",
                    "message_index": 2,
                    "summary": {
                        "included_source_count": 1,
                        "prompt_version": "v1",
                        "prompt_version_name": "v1_companion_basic",
                        "rough_context_tokens": 12,
                    },
                },
            )
            model_call.return_value = "Makes sense, tell me a little more."

            result = await run_agent_turn(
                conversation_id="conversation-1",
                messages=[{"role": "assistant", "content": "Hey, what matters to you?"}],
                user_text="Career growth and calm communication matter to me.",
                user_id="user-a",
                user_profile={"user_id": "user-a", "interested_in": "women"},
                model="llama-70b",
                agent_mode="know_me",
                agent_tone="auto",
                style_source_id=None,
            )

        self.assertTrue(result.quality_valid)
        self.assertEqual(result.messages[-1]["content"], "Makes sense, tell me a little more.")
        capture_facts.assert_called_once()
        build_context.assert_called_once_with(
            conversation_id="conversation-1",
            user_text="Career growth and calm communication matter to me.",
            user_id="user-a",
            user_profile={"user_id": "user-a", "interested_in": "women"},
            model="llama-70b",
            agent_tone="auto",
            agent_name=None,
            style_source_id=None,
            user_message_index=1,
            assistant_message_index=2,
        )
        model_call.assert_awaited_once()
        _, kwargs = model_call.call_args
        self.assertEqual(kwargs["context_sources"][0]["title"], "Profile memory")
        self.assertEqual(kwargs["user_profile"]["interested_in"], "women")
        self.assertEqual(kwargs["system_prompt"], "system prompt")
        save_snapshot.assert_called_once()
        snapshot = save_snapshot.call_args.args[0]
        self.assertEqual(snapshot["conversation_id"], "conversation-1")
        self.assertEqual(snapshot["message_index"], 2)
        self.assertEqual(snapshot["summary"]["included_source_count"], 1)
        self.assertEqual(snapshot["summary"]["prompt_version"], "v1")
        self.assertEqual(snapshot["summary"]["prompt_version_name"], "v1_companion_basic")
        save_trace.assert_called_once()
        self.assertEqual(save_trace_step.call_count, 6)
        finish_trace.assert_called_once_with(
            "trace-1",
            status="completed",
            summary={
                "ending_message_count": 3,
                "quality_valid": True,
                "reply_chars": len("Makes sense, tell me a little more."),
            },
        )

    async def test_orchestrator_keeps_message_quality_valid_while_guardrail_is_disabled(self) -> None:
        with (
            patch("agent.runtime.orchestrator.capture_profile_facts_from_user_message"),
            patch("agent.runtime.orchestrator.build_model_context_package") as build_context,
            patch("agent.runtime.orchestrator.generate_agent_reply", new_callable=AsyncMock) as model_call,
            patch("agent.runtime.orchestrator.save_agent_context_snapshot"),
            patch("agent.runtime.orchestrator.save_agent_trace") as save_trace,
            patch("agent.runtime.orchestrator.save_agent_trace_step"),
            patch("agent.runtime.orchestrator.finish_agent_trace"),
        ):
            save_trace.return_value = {"id": "trace-1"}
            build_context.return_value = ModelContextPackage(
                system_prompt="system prompt",
                context_sources=[],
                snapshot={
                    "message_index": 2,
                    "summary": {
                        "included_source_count": 0,
                        "rough_context_tokens": 0,
                    },
                },
            )
            model_call.return_value = "That does not look like a real answer."

            result = await run_agent_turn(
                conversation_id="conversation-1",
                messages=[{"role": "assistant", "content": "What are you looking for?"}],
                user_text="knl",
                user_id="user-a",
                user_profile=None,
                model="llama-70b",
                agent_mode="know_me",
                agent_tone="auto",
                style_source_id=None,
            )

        self.assertTrue(result.quality_valid)
        self.assertNotEqual(result.messages[-2].get("quality"), "low_information")


if __name__ == "__main__":
    unittest.main()
