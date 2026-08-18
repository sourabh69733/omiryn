import unittest
from unittest.mock import AsyncMock, patch

from agent.context_engine.contracts.models import ModelContextPackage
from agent.context_engine.conversation_engine.state import list_threads
from agent.providers.shared.errors import AgentProviderError, AgentProviderTruncationError
from agent.runtime.orchestrator import (
    _visible_companion_reply,
    run_agent_turn,
)
from agent.memory_engine.data_points.extraction.inline import (
    TURN_OUTPUT_V2_TOOLS,
    parse_turn_output_v2,
    turn_output_v2_tools,
)
from agent.memory_engine.data_points.extraction.inline.writer import (
    capture_turn_output_data_points,
)
from storage import (
    ENGINE,
    list_data_point_extraction_debug,
    list_profile_facts,
    profile_facts,
    reset_db,
)


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
                  "confidence": 0.86
                }
              ]
            }
            """,
            user_text="I love spicy food",
        )

        self.assertTrue(parsed.parsed)
        self.assertEqual(
            parsed.reply, "That makes sense. Spicy food tells me something about your vibe too."
        )
        self.assertEqual(parsed.data_points[0]["type"], "matching_fact")
        self.assertEqual(parsed.data_points[0]["evidence"], "I love spicy food")

    def test_shadow_tool_schema_is_isolated_and_parser_keeps_private_update(self) -> None:
        baseline = turn_output_v2_tools(include_conversation_update=False)
        shadow = turn_output_v2_tools(include_conversation_update=True)

        self.assertEqual(baseline, TURN_OUTPUT_V2_TOOLS)
        self.assertNotIn(
            "conversation_update",
            baseline[0]["function"]["parameters"]["properties"],
        )
        self.assertIn(
            "conversation_update",
            shadow[0]["function"]["parameters"]["properties"],
        )
        self.assertIn(
            "conversation_update",
            shadow[0]["function"]["parameters"]["required"],
        )
        self.assertNotIn(
            "conversation_update",
            TURN_OUTPUT_V2_TOOLS[0]["function"]["parameters"]["properties"],
        )

        parsed = parse_turn_output_v2(
            """
            {
              "reply": "That sounds exhausting.",
              "data_points": [],
              "conversation_update": {
                "user_need": "listen",
                "session_goal": "Understand the work situation",
                "thread_updates": [{"operation": "none"}]
              }
            }
            """,
            user_text="My manager keeps changing plans.",
        )
        self.assertEqual(parsed.reply, "That sounds exhausting.")
        self.assertEqual(parsed.conversation_update["user_need"], "listen")
        self.assertTrue(parsed.transport_valid)
        self.assertTrue(parsed.schema_valid)
        self.assertTrue(parsed.semantic_valid)

    def test_partial_envelope_is_transport_valid_but_not_schema_valid(self) -> None:
        parsed = parse_turn_output_v2(
            '{"reply":"I hear you.","data_points":"not-an-array"}',
            user_text="This has been difficult.",
        )

        self.assertTrue(parsed.transport_valid)
        self.assertFalse(parsed.schema_valid)
        self.assertFalse(parsed.semantic_valid)
        self.assertFalse(parsed.parsed)
        self.assertEqual(parsed.error, "schema_invalid")
        self.assertIn("data_points is required", parsed.schema_errors[0])

    def test_shadow_schema_uses_operation_specific_actions_and_explicit_none(self) -> None:
        shadow = turn_output_v2_tools(include_conversation_update=True)
        update_schema = shadow[0]["function"]["parameters"]["properties"]["conversation_update"]
        action_variants = update_schema["properties"]["thread_updates"]["items"]["oneOf"]
        variants = {
            variant["properties"]["operation"]["const"]: variant for variant in action_variants
        }

        self.assertEqual(
            set(variants),
            {"none", "create", "continue", "switch", "pause", "complete", "block"},
        )
        self.assertNotIn("thread_id", variants["create"]["properties"])
        self.assertIn("thread_id", variants["continue"]["required"])
        self.assertEqual(set(variants["none"]["properties"]), {"operation"})
        self.assertFalse(variants["block"]["additionalProperties"])

    def test_parser_falls_back_to_plain_reply_when_model_returns_normal_text(self) -> None:
        parsed = parse_turn_output_v2("Normal assistant reply.", user_text="hello")

        self.assertFalse(parsed.parsed)
        self.assertEqual(parsed.reply, "Normal assistant reply.")
        self.assertEqual(parsed.data_points, [])

    def test_parser_never_exposes_textual_function_wrapper_as_reply(self) -> None:
        parsed = parse_turn_output_v2(
            '<function(return_companion_response){"reply":"Want to talk about something else?",'
            '"data_points":[]}</function>',
            user_text="okay",
        )

        self.assertTrue(parsed.parsed)
        self.assertEqual(parsed.reply, "Want to talk about something else?")
        self.assertNotIn("<function", parsed.reply)

    def test_parser_unwraps_brace_style_function_wrapper(self) -> None:
        parsed = parse_turn_output_v2(
            '<function{return_companion_response({"reply":"Take care of yourself!",'
            '"data_points":[]})}</function>',
            user_text="I am sick today.",
        )

        self.assertTrue(parsed.parsed)
        self.assertEqual(parsed.reply, "Take care of yourself!")
        self.assertNotIn("<function", parsed.reply)

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

    def test_parser_corrects_movie_preference_misclassified_as_profile_fact(self) -> None:
        parsed = parse_turn_output_v2(
            """
            {
              "reply": "Her is a thoughtful choice.",
              "data_points": [
                {
                  "type": "profile_fact",
                  "category": "movie_preference",
                  "label": "Favorite movie",
                  "value": {"movie": "Her"},
                  "confidence": 0.96
                }
              ]
            }
            """,
            user_text="My favorite movie is Her",
        )

        self.assertEqual(parsed.data_points[0]["type"], "matching_fact")

    def test_parser_rejects_data_point_when_value_is_not_grounded_in_user_message(self) -> None:
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
                  "confidence": 0.9
                }
              ]
            }
            """,
            user_text="I am just testing today",
        )

        self.assertTrue(parsed.parsed)
        self.assertEqual(parsed.data_points, [])

    def test_parser_keeps_grounded_value_items_and_removes_hallucinated_items(self) -> None:
        parsed = parse_turn_output_v2(
            """
            {
              "reply": "Solid choices.",
              "data_points": [
                {
                  "type": "matching_fact",
                  "category": "vehicles",
                  "label": "Favorite cars",
                  "value": {
                    "liked_items": ["Toyota", "Hilux", "Fortuner", "BMW"]
                  },
                  "confidence": 0.91
                }
              ]
            }
            """,
            user_text="Toyota, hilux and fortuner",
        )

        self.assertTrue(parsed.parsed)
        self.assertEqual(len(parsed.data_points), 1)
        self.assertEqual(
            parsed.data_points[0]["value"],
            {"liked_items": ["Toyota", "Hilux", "Fortuner"]},
        )
        self.assertEqual(parsed.data_points[0]["evidence"], "Toyota, hilux and fortuner")

    def test_parser_preserves_model_extracted_label_category_and_value(self) -> None:
        parsed = parse_turn_output_v2(
            """
            {
              "reply": "That is a strong signal.",
              "data_points": [
                {
                  "type": "matching_fact",
                  "category": "partner_location_preference",
                  "label": "Prefers dating someone from a specific region",
                  "value": {"preference": "date someone from a specific region"},
                  "confidence": 0.82
                }
              ]
            }
            """,
            user_text="I want to date someone from a specific region",
        )

        point = parsed.data_points[0]
        self.assertEqual(point["type"], "matching_fact")
        self.assertEqual(point["category"], "partner_location_preference")
        self.assertEqual(point["label"], "Prefers dating someone from a specific region")
        self.assertEqual(point["value"]["preference"], "date someone from a specific region")

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
        self.assertEqual(by_key["likes_spicy_food"]["value"]["_data_point_type"], "matching_fact")
        self.assertFalse(by_key["prefers_less_interview"]["used_for_matching"])
        self.assertTrue(by_key["prefers_less_interview"]["used_for_chat_context"])
        self.assertEqual(by_key["prefers_less_interview"]["fact_type"], "chat_context_fact")
        self.assertEqual(
            by_key["prefers_less_interview"]["value"]["_data_point_type"], "chat_learning"
        )
        self.assertEqual(len(list_data_point_extraction_debug("user-a")), 3)

    def test_writer_corrects_preference_type_even_without_parser(self) -> None:
        capture_turn_output_data_points(
            conversation_id="conversation-a",
            user_id="user-a",
            user_text="I mostly enjoy sci-fi",
            message_index=2,
            data_points=[
                {
                    "type": "profile_fact",
                    "category": "movie_preference",
                    "key": "favorite_genre",
                    "label": "Favorite movie genre",
                    "value": {"genre": "sci-fi"},
                    "evidence": "I mostly enjoy sci-fi",
                    "confidence": 0.94,
                }
            ],
        )

        fact = list_profile_facts("user-a")[0]
        self.assertEqual(fact["fact_type"], "matching_fact")
        self.assertEqual(fact["value"]["_data_point_type"], "matching_fact")

    def test_legacy_misclassified_preference_is_corrected_when_read(self) -> None:
        capture_turn_output_data_points(
            conversation_id="conversation-a",
            user_id="user-a",
            user_text="My favorite movie is Her",
            message_index=2,
            data_points=[
                {
                    "type": "matching_fact",
                    "category": "movies",
                    "key": "favorite_movie",
                    "label": "Favorite movie",
                    "value": {"movie": "Her"},
                    "evidence": "My favorite movie is Her",
                    "confidence": 1.0,
                }
            ],
        )
        fact_id = list_profile_facts("user-a")[0]["id"]
        with ENGINE.begin() as connection:
            connection.execute(
                profile_facts.update()
                .where(profile_facts.c.id == fact_id)
                .values(
                    fact_type="profile_fact",
                    value_json={"movie": "Her", "_data_point_type": "profile_fact"},
                )
            )

        corrected = list_profile_facts("user-a")[0]
        self.assertEqual(corrected["fact_type"], "matching_fact")
        self.assertEqual(corrected["value"]["_data_point_type"], "matching_fact")

    async def test_orchestrator_v2_displays_reply_and_saves_hidden_data_points(self) -> None:
        with (
            patch.dict("os.environ", {"AGENT_TURN_OUTPUT_VERSION": "v2"}),
            patch("agent.runtime.orchestrator.capture_profile_facts_from_user_message"),
            patch("agent.runtime.orchestrator.build_model_context_package") as build_context,
            patch(
                "agent.runtime.orchestrator.generate_agent_reply", new_callable=AsyncMock
            ) as model_call,
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

        self.assertEqual(
            result.messages[-1]["content"], "Nice, spicy food gives me a small but useful signal."
        )
        self.assertEqual(model_call.call_args.kwargs["system_prompt"], "system prompt")
        self.assertNotIn("response_format", model_call.call_args.kwargs)
        tools = model_call.call_args.kwargs["tools"]
        self.assertEqual(tools[0]["function"]["name"], "return_companion_response")
        self.assertNotIn(
            "evidence",
            tools[0]["function"]["parameters"]["properties"]["data_points"]["items"]["properties"],
        )
        self.assertEqual(
            model_call.call_args.kwargs["tool_choice"],
            {"type": "function", "function": {"name": "return_companion_response"}},
        )
        facts = list_profile_facts("user-a")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["label"], "Likes spicy food")
        self.assertEqual(facts[0]["source_kind"], "agent_turn_output_v2")

    async def test_orchestrator_records_valid_thread_proposal_without_persisting_it(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {
                    "AGENT_TURN_OUTPUT_VERSION": "v2",
                    "CONVERSATION_STATE_V2_ENABLED": "true",
                    "CONVERSATION_STATE_V2_SHADOW_ENABLED": "true",
                },
            ),
            patch("agent.runtime.orchestrator.capture_profile_facts_from_user_message"),
            patch("agent.runtime.orchestrator.build_model_context_package") as build_context,
            patch(
                "agent.runtime.orchestrator.generate_agent_reply", new_callable=AsyncMock
            ) as model_call,
            patch("agent.runtime.orchestrator.save_agent_context_snapshot"),
            patch("agent.runtime.orchestrator.save_agent_trace") as save_trace,
            patch("agent.runtime.orchestrator.save_agent_trace_step") as save_trace_step,
            patch("agent.runtime.orchestrator.finish_agent_trace"),
        ):
            save_trace.return_value = {"id": "trace-shadow"}
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
              "reply": "That uncertainty sounds genuinely tiring.",
              "data_points": [],
              "conversation_update": {
                "user_need": "listen",
                "session_goal": "Understand the user's work stress",
                "thread_updates": [
                  {
                    "operation": "create",
                    "title": "Stress with manager",
                    "summary": "The user's manager repeatedly changes plans.",
                    "origin": "user_started",
                    "depth": "mentioned",
                    "user_interest": "high",
                    "salience": 0.8
                  }
                ]
              }
            }
            """

            result = await run_agent_turn(
                conversation_id="conversation-a",
                messages=[{"role": "assistant", "content": "What happened at work?"}],
                user_text="My manager keeps changing plans and it is exhausting.",
                user_id="user-a",
                user_profile=None,
                model="llama-70b",
                agent_mode="know_me",
                agent_tone="auto",
                style_source_id=None,
            )

        self.assertEqual(
            result.messages[-1]["content"], "That uncertainty sounds genuinely tiring."
        )
        tool_parameters = model_call.call_args.kwargs["tools"][0]["function"]["parameters"]
        self.assertIn("conversation_update", tool_parameters["properties"])
        model_step = next(
            call.args[0]
            for call in save_trace_step.call_args_list
            if call.args[0]["step_name"] == "model_call"
        )
        shadow = model_step["metadata"]["turn_output_v2"]["conversation_state_shadow"]
        self.assertTrue(shadow["valid"])
        self.assertFalse(shadow["persisted"])
        self.assertEqual(shadow["proposed_thread_update_count"], 1)
        self.assertEqual(list_threads("user-a"), [])

    def test_private_transport_is_never_accepted_as_visible_chat_text(self) -> None:
        with self.assertRaises(AgentProviderError):
            _visible_companion_reply('<function(return_companion_response){"reply":')

    async def test_orchestrator_retries_plain_reply_after_structured_output_truncation(
        self,
    ) -> None:
        with (
            patch.dict("os.environ", {"AGENT_TURN_OUTPUT_VERSION": "v2"}),
            patch("agent.runtime.orchestrator.capture_profile_facts_from_user_message"),
            patch("agent.runtime.orchestrator.build_model_context_package") as build_context,
            patch(
                "agent.runtime.orchestrator.generate_agent_reply",
                new_callable=AsyncMock,
                side_effect=[
                    AgentProviderTruncationError("length"),
                    "Tell me more about what made that important to you.",
                ],
            ) as model_call,
            patch("agent.runtime.orchestrator.save_agent_context_snapshot"),
            patch("agent.runtime.orchestrator.save_agent_trace") as save_trace,
            patch("agent.runtime.orchestrator.save_agent_trace_step") as save_trace_step,
            patch("agent.runtime.orchestrator.finish_agent_trace"),
        ):
            save_trace.return_value = {"id": "trace-fallback"}
            build_context.return_value = ModelContextPackage(
                system_prompt="system prompt",
                context_sources=[],
                snapshot={
                    "conversation_id": "conversation-a",
                    "message_index": 2,
                    "summary": {"included_source_count": 0, "rough_context_tokens": 0},
                },
            )

            result = await run_agent_turn(
                conversation_id="conversation-a",
                messages=[],
                user_text="It mattered because she understood me.",
                user_id="user-a",
                user_profile=None,
                model="llama-70b",
                agent_mode="know_me",
                agent_tone="auto",
                style_source_id=None,
            )

        self.assertEqual(
            result.messages[-1]["content"],
            "Tell me more about what made that important to you.",
        )
        self.assertEqual(model_call.await_count, 2)
        self.assertIsNotNone(model_call.await_args_list[0].kwargs["tools"])
        self.assertNotIn("tools", model_call.await_args_list[1].kwargs)
        self.assertEqual(model_call.await_args_list[1].kwargs["max_tokens"], 400)
        model_step = next(
            call.args[0]
            for call in save_trace_step.call_args_list
            if call.args[0]["step_name"] == "model_call"
        )
        self.assertEqual(
            model_step["metadata"]["turn_output_v2"]["error"],
            "output_truncated",
        )

    async def test_orchestrator_retries_before_malformed_transport_reaches_ui(self) -> None:
        with (
            patch.dict("os.environ", {"AGENT_TURN_OUTPUT_VERSION": "v2"}),
            patch("agent.runtime.orchestrator.capture_profile_facts_from_user_message"),
            patch("agent.runtime.orchestrator.build_model_context_package") as build_context,
            patch(
                "agent.runtime.orchestrator.generate_agent_reply",
                new_callable=AsyncMock,
                side_effect=[
                    '<function(return_companion_response){"reply":"cut off',
                    "I lost my train of thought—what part mattered most?",
                ],
            ) as model_call,
            patch("agent.runtime.orchestrator.save_agent_context_snapshot"),
            patch("agent.runtime.orchestrator.save_agent_trace") as save_trace,
            patch("agent.runtime.orchestrator.save_agent_trace_step"),
            patch("agent.runtime.orchestrator.finish_agent_trace"),
        ):
            save_trace.return_value = {"id": "trace-malformed"}
            build_context.return_value = ModelContextPackage(
                system_prompt="system prompt",
                context_sources=[],
                snapshot={
                    "conversation_id": "conversation-a",
                    "message_index": 2,
                    "summary": {"included_source_count": 0, "rough_context_tokens": 0},
                },
            )

            result = await run_agent_turn(
                conversation_id="conversation-a",
                messages=[],
                user_text="I had a difficult day.",
                user_id="user-a",
                user_profile=None,
                model="llama-70b",
                agent_mode="know_me",
                agent_tone="auto",
                style_source_id=None,
            )

        self.assertEqual(
            result.messages[-1]["content"],
            "I lost my train of thought—what part mattered most?",
        )
        self.assertEqual(model_call.await_count, 2)
