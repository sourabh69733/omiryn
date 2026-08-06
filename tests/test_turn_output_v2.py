import unittest
from unittest.mock import AsyncMock, patch

from agent.context_engine.models import ModelContextPackage
from agent.runtime.orchestrator import run_agent_turn
from agent.runtime.turn_output import parse_turn_output_v2
from agent.runtime.turn_output.writer import capture_turn_output_data_points
from storage import list_data_point_extraction_debug, list_profile_facts, reset_db


class TurnOutputV2Test(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()

    def tearDown(self) -> None:
        reset_db()

    def test_parser_extracts_reply_and_user_evidenced_data_points(self) -> None:
        parsed = parse_turn_output_v2(
            """
            {
              "reply": "That makes sense. Spicy food tells me something about your vibe too.",
              "data_points": [
                {
                  "type": "matching_fact",
                  "category": "food_preferences",
                  "label": "Likes spicy food",
                  "value": {"preference": "spicy food"},
                  "evidence": "I love spicy food",
                  "confidence": 0.86
                }
              ]
            }
            """,
            user_text="I love spicy food",
        )

        self.assertTrue(parsed.parsed)
        self.assertEqual(parsed.reply, "That makes sense. Spicy food tells me something about your vibe too.")
        self.assertEqual(parsed.data_points[0]["type"], "matching_fact")
        self.assertEqual(parsed.data_points[0]["evidence"], "I love spicy food")

    def test_parser_falls_back_to_plain_reply_when_model_returns_normal_text(self) -> None:
        parsed = parse_turn_output_v2("Normal assistant reply.", user_text="hello")

        self.assertFalse(parsed.parsed)
        self.assertEqual(parsed.reply, "Normal assistant reply.")
        self.assertEqual(parsed.data_points, [])

    def test_parser_accepts_fenced_json_with_nested_value_objects(self) -> None:
        parsed = parse_turn_output_v2(
            """
            ```json
            {
              "reply": "Noted.",
              "data_points": [
                {
                  "type": "profile_fact",
                  "category": "location",
                  "label": "Lives in Bengaluru",
                  "value": {"city": "Bengaluru", "country": "India"},
                  "evidence": "I live in Bengaluru",
                  "confidence": 0.91
                }
              ]
            }
            ```
            """,
            user_text="I live in Bengaluru",
        )

        self.assertTrue(parsed.parsed)
        self.assertEqual(parsed.reply, "Noted.")
        self.assertEqual(parsed.data_points[0]["value"]["city"], "Bengaluru")

    def test_parser_rejects_data_point_without_user_message_evidence(self) -> None:
        parsed = parse_turn_output_v2(
            """
            {
              "reply": "Got it.",
              "data_points": [
                {
                  "type": "matching_fact",
                  "category": "values",
                  "label": "Likes honesty",
                  "value": {"value": "honesty"},
                  "evidence": "Honesty matters",
                  "confidence": 0.9
                }
              ]
            }
            """,
            user_text="I am just testing today",
        )

        self.assertTrue(parsed.parsed)
        self.assertEqual(parsed.data_points, [])

    def test_writer_saves_supported_types_and_skips_do_not_store(self) -> None:
        result = capture_turn_output_data_points(
            conversation_id="conversation-a",
            user_id="user-a",
            user_text="I love spicy food but do not remember this joke.",
            message_index=2,
            data_points=[
                {
                    "type": "matching_fact",
                    "category": "food_preferences",
                    "key": "likes_spicy_food",
                    "label": "Likes spicy food",
                    "value": {"preference": "spicy food"},
                    "evidence": "I love spicy food",
                    "confidence": 0.84,
                },
                {
                    "type": "chat_learning",
                    "category": "conversation_style",
                    "key": "prefers_less_interview",
                    "label": "Prefers fewer interview-like questions",
                    "value": {"style": "fewer questions"},
                    "evidence": "do not remember this joke",
                    "confidence": 0.55,
                },
                {
                    "type": "do_not_store",
                    "category": "privacy",
                    "key": "private_joke",
                    "label": "Do not store joke",
                    "value": {"detail": "joke"},
                    "evidence": "do not remember this joke",
                    "confidence": 0.99,
                },
            ],
        )

        facts = list_profile_facts("user-a")
        self.assertEqual(result["saved_count"], 2)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(len(facts), 2)
        by_key = {fact["key"]: fact for fact in facts}
        self.assertTrue(by_key["likes_spicy_food"]["used_for_matching"])
        self.assertFalse(by_key["prefers_less_interview"]["used_for_matching"])
        self.assertTrue(by_key["prefers_less_interview"]["used_for_chat_context"])
        self.assertEqual(by_key["prefers_less_interview"]["fact_type"], "chat_context_fact")
        self.assertEqual(len(list_data_point_extraction_debug("user-a")), 3)

    async def test_orchestrator_v2_displays_reply_and_saves_hidden_data_points(self) -> None:
        with (
            patch.dict("os.environ", {"AGENT_TURN_OUTPUT_VERSION": "v2"}),
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
                    "conversation_id": "conversation-a",
                    "message_index": 2,
                    "summary": {"included_source_count": 0, "rough_context_tokens": 0},
                },
            )
            model_call.return_value = """
            {
              "reply": "Nice, spicy food gives me a small but useful signal.",
              "data_points": [
                {
                  "type": "matching_fact",
                  "category": "food_preferences",
                  "label": "Likes spicy food",
                  "value": {"preference": "spicy food"},
                  "evidence": "I love spicy food",
                  "confidence": 0.84
                }
              ]
            }
            """

            result = await run_agent_turn(
                conversation_id="conversation-a",
                messages=[{"role": "assistant", "content": "Tell me one small thing about you."}],
                user_text="I love spicy food",
                user_id="user-a",
                user_profile=None,
                model="llama-70b",
                agent_mode="know_me",
                agent_tone="auto",
                style_source_id=None,
            )

        self.assertEqual(result.messages[-1]["content"], "Nice, spicy food gives me a small but useful signal.")
        self.assertIn("Return ONLY one JSON object", model_call.call_args.kwargs["system_prompt"])
        facts = list_profile_facts("user-a")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["label"], "Likes spicy food")
        self.assertEqual(facts[0]["source_kind"], "agent_turn_output_v2")
