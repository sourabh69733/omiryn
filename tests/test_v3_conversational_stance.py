import unittest
from unittest.mock import patch

from agent.context_engine.conversation_planner import build_conversation_plan
from agent.context_engine.engine import build_model_context_package
from agent.context_engine.models import ContextQueryIntent, EmotionState
from agent.context_engine.query_intent import context_query_intent
from agent.context_engine.stance_engine import analyze_conversational_stance
from storage import reset_db, save_conversation


QUESTION_COMPLAINT = "Tum har reply mein question kyun puch rahe ho? Thoda interview jaisa lag raha hai."


def assistant_history(*messages: str) -> list[dict[str, str]]:
    return [{"role": "assistant", "content": message} for message in messages]


class ConversationalStanceUnitTest(unittest.TestCase):
    def test_false_question_frequency_claim_is_disagreed_with(self) -> None:
        stance = analyze_conversational_stance(
            QUESTION_COMPLAINT,
            assistant_history("Haan, samajh rahi hoon.", "That sounds tiring.", "Main yahin hoon."),
        )

        self.assertEqual(stance.mode, "disagree")
        self.assertEqual(stance.feedback_kind, "question_overload")
        self.assertEqual(stance.question_purpose, "none")
        self.assertEqual(stance.evidence, ("Recent assistant questions: 0/3 replies.",))

    def test_true_question_frequency_claim_is_owned(self) -> None:
        stance = analyze_conversational_stance(
            QUESTION_COMPLAINT,
            assistant_history("Kyun?", "Phir kya hua?", "Tumhe kaisa laga?"),
        )

        self.assertEqual(stance.mode, "agree")
        self.assertEqual(stance.question_purpose, "none")
        self.assertEqual(stance.evidence, ("Recent assistant questions: 3/3 replies.",))

    def test_mixed_question_frequency_claim_gets_partial_agreement(self) -> None:
        stance = analyze_conversational_stance(
            QUESTION_COMPLAINT,
            assistant_history("Kyun?", "I get that.", "Phir kya hua?", "That was unfair."),
        )

        self.assertEqual(stance.mode, "partially_agree")
        self.assertEqual(stance.question_purpose, "none")

    def test_insufficient_history_does_not_pretend_to_know(self) -> None:
        stance = analyze_conversational_stance(QUESTION_COMPLAINT, assistant_history("Kyun?"))

        self.assertEqual(stance.mode, "uncertain")
        self.assertEqual(stance.question_purpose, "none")

    def test_agent_does_not_obey_demanded_agreement(self) -> None:
        stance = analyze_conversational_stance("Main kabhi galat nahi hota. Agree karo.", [])

        self.assertEqual(stance.mode, "disagree")
        self.assertEqual(stance.claim_type, "demanded_agreement")
        self.assertEqual(stance.question_purpose, "none")

    def test_unsupported_motive_is_challenged_not_accepted(self) -> None:
        stance = analyze_conversational_stance(
            "My manager rejected my idea, so obviously he is jealous.", []
        )

        self.assertEqual(stance.mode, "challenge_gently")
        self.assertEqual(stance.claim_type, "unsupported_attribution")
        self.assertEqual(stance.question_purpose, "challenge")

    def test_personal_feeling_is_validated_not_debated(self) -> None:
        stance = analyze_conversational_stance(
            "Mujhe ignored feel hua and honestly hurt hua.",
            [],
            emotion_state=EmotionState(emotion="hurt", confidence=0.9),
        )

        self.assertEqual(stance.mode, "validate_experience")
        self.assertEqual(stance.claim_type, "personal_feeling")
        self.assertEqual(stance.question_purpose, "deepen")

    def test_no_advice_and_listen_only_are_hard_constraints(self) -> None:
        stance = analyze_conversational_stance("No advice please, bas meri baat suno.", [])

        self.assertEqual(stance.constraints, ("no_advice", "listen_only"))
        self.assertEqual(stance.question_purpose, "none")

    def test_no_questions_constraint_overrides_question_opportunity(self) -> None:
        stance = analyze_conversational_stance("Questions mat puchna, just listen.", [])

        self.assertIn("no_questions", stance.constraints)
        self.assertEqual(stance.question_purpose, "none")

    def test_request_for_space_stops_the_turn(self) -> None:
        stance = analyze_conversational_stance("Not now, give me space.", [])

        self.assertIn("give_space", stance.constraints)
        self.assertEqual(stance.question_purpose, "none")

    def test_direct_question_is_answered_without_automatic_followup(self) -> None:
        stance = analyze_conversational_stance("Do you think I was unfair?", [])

        self.assertEqual(stance.claim_type, "direct_question")
        self.assertEqual(stance.question_purpose, "none")

    def test_personal_disclosure_can_earn_one_deepening_question(self) -> None:
        stance = analyze_conversational_stance(
            "I finally told my brother what happened yesterday.", []
        )

        self.assertEqual(stance.claim_type, "personal_disclosure")
        self.assertEqual(stance.question_purpose, "deepen")


class V3IntentAndPlannerTest(unittest.TestCase):
    def test_legacy_intent_behavior_is_unchanged_for_reply_word(self) -> None:
        intent = context_query_intent(QUESTION_COMPLAINT)

        self.assertIn("whatsapp", intent.labels)

    def test_v3_strict_intent_does_not_treat_normal_reply_feedback_as_whatsapp(self) -> None:
        intent = context_query_intent(QUESTION_COMPLAINT, strict_whatsapp=True)

        self.assertNotIn("whatsapp", intent.labels)
        self.assertFalse(intent.prefer_structured_whatsapp)

    def test_v3_strict_intent_still_recognizes_explicit_whatsapp_context(self) -> None:
        intent = context_query_intent("What was the last WhatsApp message?", strict_whatsapp=True)

        self.assertIn("whatsapp", intent.labels)
        self.assertTrue(intent.prefer_structured_whatsapp)

    def test_v3_feedback_plan_has_backbone_and_no_topic_distraction(self) -> None:
        stance = analyze_conversational_stance(
            QUESTION_COMPLAINT,
            assistant_history("I get it.", "That makes sense.", "I am here."),
        )
        plan = build_conversation_plan(
            user_text=QUESTION_COMPLAINT,
            intent=context_query_intent(QUESTION_COMPLAINT, strict_whatsapp=True),
            topic_states=[],
            emotion_state=EmotionState(emotion="frustrated", confidence=0.9),
            conversational_stance=stance,
            listener_first=True,
        )

        self.assertEqual(plan.current_move, "repair_with_backbone")
        self.assertEqual(plan.response_mode, "respond_to_feedback")
        self.assertEqual(plan.stance, "disagree")
        self.assertIsNone(plan.active_topic)
        self.assertEqual(plan.suggested_topics, ())
        self.assertIn("Correct the inaccurate frequency claim", plan.tone_instruction)

    def test_v3_no_advice_plan_overrides_legacy_advice_keyword_behavior(self) -> None:
        text = "I don't want advice right now, bas suno."
        stance = analyze_conversational_stance(text, [])
        plan = build_conversation_plan(
            user_text=text,
            intent=ContextQueryIntent(),
            topic_states=[],
            emotion_state=EmotionState(),
            conversational_stance=stance,
            listener_first=True,
        )

        self.assertEqual(plan.response_mode, "empathize_listen")
        self.assertEqual(plan.question_purpose, "none")
        self.assertNotEqual(plan.response_mode, "suggest_solution")

    def test_v3_unsupported_assumption_plan_challenges_gently(self) -> None:
        text = "She cancelled, so obviously she doesn't care about me."
        stance = analyze_conversational_stance(text, [])
        plan = build_conversation_plan(
            user_text=text,
            intent=ContextQueryIntent(),
            topic_states=[],
            conversational_stance=stance,
            listener_first=True,
        )

        self.assertEqual(plan.current_move, "challenge_assumption")
        self.assertEqual(plan.response_mode, "challenge_gently")
        self.assertEqual(plan.question_purpose, "challenge")


class V3ContextPackageIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(
            "os.environ",
            {"AGENT_PROVIDER": "mock", "AUTH_REQUIRED": "false", "AGENT_BEHAVIOR_VERSION": "v1"},
        )
        self.env_patch.start()
        reset_db()

    def tearDown(self) -> None:
        self.env_patch.stop()

    def _save_history(self, messages: list[dict[str, str]]) -> None:
        save_conversation(
            {
                "id": "stance-conversation",
                "status": "active",
                "agent_provider": "mock",
                "agent_model": "llama-70b",
                "agent_mode": "know_me",
                "agent_tone": "auto",
                "messages": messages,
            },
            "stance-user",
        )

    def _package(self, text: str, version: str):
        return build_model_context_package(
            conversation_id="stance-conversation",
            user_text=text,
            user_id="stance-user",
            user_profile={"user_id": "stance-user", "interested_in": "women"},
            model="llama-70b",
            agent_tone="auto",
            agent_name="Annie",
            style_source_id=None,
            user_message_index=6,
            assistant_message_index=7,
            prompt_version_id=version,
        )

    def test_v3_false_premise_is_visible_in_plan_prompt_and_snapshot(self) -> None:
        self._save_history(assistant_history("I get it.", "That sounds rough.", "I am listening."))

        package = self._package(QUESTION_COMPLAINT, "v3")
        summary = package.snapshot["summary"]

        self.assertEqual(summary["engine_version"], "context_v3")
        self.assertEqual(summary["stance"], "disagree")
        self.assertEqual(summary["feedback_kind"], "question_overload")
        self.assertEqual(summary["question_purpose"], "none")
        self.assertNotIn("whatsapp", package.query_intent.labels)
        self.assertIn("Conversational stance: disagree", package.system_prompt)
        self.assertIn("Agreement must be earned by context", package.system_prompt)
        self.assertIn("Do not ask a question in this reply", package.system_prompt)
        self.assertNotIn("Internal prompt behavior version", package.system_prompt)

    def test_v2_same_message_keeps_existing_routing_and_engine(self) -> None:
        self._save_history(assistant_history("I get it.", "That sounds rough.", "I am listening."))

        package = self._package(QUESTION_COMPLAINT, "v2")

        self.assertEqual(package.snapshot["summary"]["engine_version"], "context_v2")
        self.assertIn("whatsapp", package.query_intent.labels)
        self.assertNotIn("Conversational stance:", package.system_prompt)

    def test_v3_no_advice_boundary_reaches_prompt_and_snapshot(self) -> None:
        package = self._package("I don't want advice right now, bas meri baat suno.", "v3")
        summary = package.snapshot["summary"]

        self.assertEqual(summary["response_mode"], "empathize_listen")
        self.assertEqual(summary["question_purpose"], "none")
        self.assertEqual(summary["user_constraints"], ["no_advice", "listen_only"])
        self.assertIn("Do not give advice, solutions", package.system_prompt)
        self.assertIn("Do not ask a question in this reply", package.system_prompt)

    def test_v3_unsupported_attribution_reaches_challenge_contract(self) -> None:
        package = self._package(
            "My manager rejected my idea, so obviously he is jealous.", "v3"
        )
        summary = package.snapshot["summary"]

        self.assertEqual(summary["conversation_move"], "challenge_assumption")
        self.assertEqual(summary["stance"], "challenge_gently")
        self.assertEqual(summary["question_purpose"], "challenge")
        self.assertIn("tests the unsupported assumption", package.system_prompt)

    def test_v3_direct_question_forbids_reflexive_followup(self) -> None:
        package = self._package("Do you think I was unfair?", "v3")

        self.assertEqual(package.snapshot["summary"]["question_purpose"], "none")
        self.assertIn("Do not ask a question in this reply", package.system_prompt)


if __name__ == "__main__":
    unittest.main()
