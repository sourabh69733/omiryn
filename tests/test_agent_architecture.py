import unittest
from unittest.mock import AsyncMock, patch

from agent.context_engine.context import AgentContext
from agent.runtime.orchestrator import run_agent_turn


class AgentArchitectureTest(unittest.IsolatedAsyncioTestCase):
    async def test_orchestrator_builds_context_before_calling_model(self) -> None:
        with (
            patch("agent.runtime.orchestrator.capture_profile_facts_from_user_message") as capture_facts,
            patch("agent.runtime.orchestrator.build_reply_context") as build_context,
            patch("agent.runtime.orchestrator.generate_agent_reply", new_callable=AsyncMock) as model_call,
            patch("agent.runtime.orchestrator.save_agent_context_snapshot") as save_snapshot,
        ):
            build_context.return_value = AgentContext(
                user_profile={"user_id": "user-a", "interested_in": "women"},
                context_sources=[
                    {
                        "id": "source-1",
                        "source_type": "llm_profile",
                        "title": "Profile memory",
                        "content": "Career growth matters.",
                    }
                ],
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
            "conversation-1",
            "Career growth and calm communication matter to me.",
            user_id="user-a",
            user_profile={"user_id": "user-a", "interested_in": "women"},
            style_source_id=None,
        )
        model_call.assert_awaited_once()
        _, kwargs = model_call.call_args
        self.assertEqual(kwargs["context_sources"][0]["title"], "Profile memory")
        self.assertEqual(kwargs["user_profile"]["interested_in"], "women")
        save_snapshot.assert_called_once()
        snapshot = save_snapshot.call_args.args[0]
        self.assertEqual(snapshot["conversation_id"], "conversation-1")
        self.assertEqual(snapshot["message_index"], 2)
        self.assertEqual(snapshot["summary"]["included_source_count"], 1)

    async def test_orchestrator_marks_low_information_messages(self) -> None:
        with (
            patch("agent.runtime.orchestrator.capture_profile_facts_from_user_message"),
            patch("agent.runtime.orchestrator.build_reply_context") as build_context,
            patch("agent.runtime.orchestrator.generate_agent_reply", new_callable=AsyncMock) as model_call,
            patch("agent.runtime.orchestrator.save_agent_context_snapshot"),
        ):
            build_context.return_value = AgentContext()
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

        self.assertFalse(result.quality_valid)
        self.assertEqual(result.messages[-2]["quality"], "low_information")


if __name__ == "__main__":
    unittest.main()
