import unittest

from agent.context_engine.engine import build_model_context_package
from agent.context_engine.conversation_engine.planning import build_conversation_plan
from agent.context_engine.contracts.models import ContextQueryIntent, ConversationalStance, EmotionState
from agent.context_engine.assembly.matching import (
    MATCHING_DIMENSIONS,
    calculate_matching_understanding,
)
from agent.memory_engine.data_points import normalize_data_point
from storage import reset_db, upsert_profile_fact


def matching_fact(
    category: str,
    *,
    key: str | None = None,
    confidence: float = 0.8,
    confidence_state: str = "active",
    evidence: list[dict[str, object]] | None = None,
    status: str = "active",
    used_for_matching: bool = True,
) -> dict[str, object]:
    return {
        "user_id": "matching-user",
        "category": category,
        "key": key or category,
        "label": f"Signal for {category}",
        "value": {"detail": category},
        "confidence": confidence,
        "confidence_state": confidence_state,
        "source_kind": "agent_turn_output_v2",
        "source_id": "matching-conversation",
        "evidence": evidence
        if evidence is not None
        else [{"conversation_id": "matching-conversation", "message_index": 1, "text": category}],
        "status": status,
        "visibility": "internal",
        "fact_type": "matching_fact",
        "used_for_matching": used_for_matching,
        "used_for_chat_context": True,
    }


class MatchingUnderstandingUnitTest(unittest.TestCase):
    def test_empty_profile_starts_with_every_dimension_unexplored(self) -> None:
        progress = calculate_matching_understanding([])

        self.assertEqual(progress.level, "starting")
        self.assertEqual(progress.breadth_percent, 0)
        self.assertEqual(progress.depth_percent, 0)
        self.assertEqual(progress.foundation_covered, 0)
        self.assertEqual(progress.unexplored_dimensions, MATCHING_DIMENSIONS)

    def test_existing_interested_in_profile_counts_as_confirmed_desired_partner(self) -> None:
        progress = calculate_matching_understanding(
            [],
            user_profile={"interested_in": "women"},
        )
        desired_partner = next(
            item for item in progress.dimensions if item.id == "desired_partner"
        )

        self.assertEqual(desired_partner.depth, "deep")
        self.assertEqual(progress.foundation_covered, 1)

    def test_three_foundation_areas_reach_soft_basic_level(self) -> None:
        progress = calculate_matching_understanding(
            [
                matching_fact("relationship_intent"),
                matching_fact("age_preference"),
                matching_fact("location_preference"),
            ]
        )

        self.assertEqual(progress.level, "basic")
        self.assertEqual(progress.foundation_covered, 3)
        self.assertIn("desired_partner", progress.unexplored_dimensions)

    def test_useful_level_needs_breadth_beyond_foundation(self) -> None:
        progress = calculate_matching_understanding(
            [
                matching_fact("relationship_intent"),
                matching_fact("desired_partner"),
                matching_fact("age_preference"),
                matching_fact("location_preference"),
                matching_fact("values"),
                matching_fact("lifestyle"),
                matching_fact("communication"),
            ]
        )

        self.assertEqual(progress.level, "useful")
        self.assertEqual(progress.foundation_covered, 4)

    def test_repeated_evidence_deepens_a_dimension(self) -> None:
        progress = calculate_matching_understanding(
            [
                matching_fact(
                    "partner_qualities",
                    evidence=[
                        {"conversation_id": "c", "message_index": 1, "text": "kind"},
                        {"conversation_id": "c", "message_index": 5, "text": "emotionally mature"},
                    ],
                )
            ]
        )
        personality = next(
            item for item in progress.dimensions if item.id == "desired_personality"
        )

        self.assertEqual(personality.depth, "deep")
        self.assertEqual(personality.evidence_count, 2)
        self.assertNotIn("desired_personality", progress.can_deepen_dimensions)

    def test_candidate_fact_is_only_mentioned(self) -> None:
        progress = calculate_matching_understanding(
            [matching_fact("location_preference", confidence=0.95, confidence_state="candidate")]
        )
        location = next(
            item for item in progress.dimensions if item.id == "location_preference"
        )

        self.assertEqual(location.depth, "mentioned")
        self.assertIn("location_preference", progress.can_deepen_dimensions)

    def test_rejected_and_non_matching_facts_do_not_advance_progress(self) -> None:
        progress = calculate_matching_understanding(
            [
                matching_fact("relationship_intent", status="rejected"),
                matching_fact("age_preference", used_for_matching=False),
            ]
        )

        self.assertEqual(progress.level, "starting")
        self.assertEqual(progress.foundation_covered, 0)

    def test_labels_and_evidence_are_not_keyword_scanned(self) -> None:
        fact = matching_fact("other", key="miscellaneous")
        fact["label"] = "Wants a serious partner from Bengaluru aged 25 to 30"
        fact["evidence"] = [{"text": "I want a serious partner from Bengaluru aged 25 to 30"}]

        progress = calculate_matching_understanding([fact])

        self.assertEqual(progress.foundation_covered, 0)
        self.assertEqual(progress.known_dimensions, ())

    def test_listener_first_planner_receives_a_private_discovery_hint_when_open(self) -> None:
        progress = calculate_matching_understanding(
            [matching_fact("location_preference", confidence=0.5)]
        )

        plan = build_conversation_plan(
            user_text="I have a quiet evening today.",
            intent=ContextQueryIntent(),
            topic_states=[],
            emotion_state=EmotionState(),
            conversational_stance=ConversationalStance(),
            matching_understanding=progress,
            listener_first=True,
        )

        self.assertTrue(plan.matching_discovery_allowed)
        self.assertEqual(plan.matching_discovery_topics[0], "location_preference")
        self.assertIn("relationship_intent", plan.matching_discovery_topics)

    def test_listener_first_planner_defers_discovery_for_a_listening_boundary(self) -> None:
        progress = calculate_matching_understanding([matching_fact("location_preference")])

        plan = build_conversation_plan(
            user_text="Bas meri baat suno, questions mat puchna.",
            intent=ContextQueryIntent(),
            topic_states=[],
            emotion_state=EmotionState(),
            conversational_stance=ConversationalStance(constraints=("listen_only", "no_questions")),
            matching_understanding=progress,
            listener_first=True,
        )

        self.assertFalse(plan.matching_discovery_allowed)
        self.assertEqual(plan.matching_discovery_topics, ())


class MatchingUnderstandingContextIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()

    def test_v3_1_adds_quiet_progress_awareness_without_changing_v3(self) -> None:
        upsert_profile_fact(normalize_data_point(matching_fact("relationship_intent")))
        profile = {"user_id": "matching-user", "interested_in": "women"}
        common = {
            "conversation_id": "matching-conversation",
            "user_text": "Today was exhausting, bas meri baat suno.",
            "user_id": "matching-user",
            "user_profile": profile,
            "model": "llama-70b",
            "agent_tone": "auto",
            "agent_name": "Annie",
            "style_source_id": None,
            "user_message_index": 0,
            "assistant_message_index": 1,
        }

        v3 = build_model_context_package(**common, prompt_version_id="v3")
        v3_1 = build_model_context_package(**common, prompt_version_id="v3-1")

        self.assertEqual(v3_1.prompt_version, "v3-1")
        self.assertEqual(v3_1.snapshot["summary"]["engine_version"], "context_v3_1")
        self.assertEqual(v3_1.snapshot["summary"]["matching_foundation_covered"], 2)
        self.assertEqual(v3_1.snapshot["context"]["matching_understanding"]["level"], "starting")
        self.assertIn("listen_only", v3_1.snapshot["summary"]["user_constraints"])
        self.assertFalse(v3_1.snapshot["summary"]["matching_discovery_allowed"])
        self.assertEqual(
            v3_1.snapshot["context"]["conversation_plan"]["matching_discovery_topics"],
            [],
        )
        self.assertNotIn("## Matching Understanding", v3.system_prompt)
        self.assertIn("## Matching Understanding", v3_1.system_prompt)
        self.assertIn("Current understanding level: starting", v3_1.system_prompt)
        self.assertIn("Foundation understood: 2 of 5", v3_1.system_prompt)
        self.assertIn("Known areas: relationship intent, desired partner", v3_1.system_prompt)
        self.assertIn("not a checklist, target, or completion gate", v3_1.system_prompt)
        self.assertIn("Do not ask about a missing area merely because it is missing", v3_1.system_prompt)
        self.assertNotIn("matching_understanding", v3.snapshot["context"])


if __name__ == "__main__":
    unittest.main()
