"""Friends-first: the companion never steers toward romance or flirting with the user."""

import unittest

from fastapi.testclient import TestClient

from agent.context_engine.assembly.matching import calculate_matching_understanding
from agent.context_engine.contracts.models import (
    ContextQueryIntent,
    ConversationalStance,
    EmotionState,
    ThreadGuidance,
    ThreadReference,
)
from agent.context_engine.conversation_engine.planning import build_conversation_plan
from agent.context_engine.conversation_engine.planning.planner import COMMON_STARTER_TOPIC_POLICY
from agent.context_engine.prompt_engine.modules.boredom_recovery import boredom_recovery_prompt
from agent.context_engine.prompt_engine.modules.safety import safety_module_prompt
from agent.context_engine.contracts.models import ConversationPlan
from storage import get_user_profile, reset_db, save_user_profile

ROMANCE_WORDS = ("romantic", "flirt", "intimacy", "dating", "partner attention")


class FriendsFirstPromptTest(unittest.TestCase):
    def test_starter_policy_does_not_steer_to_romance(self) -> None:
        text = " ".join(COMMON_STARTER_TOPIC_POLICY).casefold()
        for word in ROMANCE_WORDS:
            self.assertNotIn(word, text)

    def _plan(self, text: str, labels: tuple[str, ...] = (), guidance: ThreadGuidance | None = None):
        return build_conversation_plan(
            user_text=text,
            intent=ContextQueryIntent(labels=labels, is_low_information="low_information" in labels),
            emotion_state=EmotionState(),
            conversational_stance=ConversationalStance(),
            matching_understanding=calculate_matching_understanding({"humor": "Likes deadpan jokes."}),
            thread_guidance=guidance,
            listener_first=True,
        )

    def test_bored_user_gets_open_vibe_areas_as_fresh_angles(self) -> None:
        plan = self._plan("hmm", labels=("low_information",))

        self.assertTrue(plan.suggested_topics)
        self.assertIn("what they want from a friend", plan.suggested_topics[0])
        self.assertNotIn("make them laugh", " ".join(plan.suggested_topics))
        self.assertEqual(plan.data_targets, ())

    def test_no_fresh_angles_when_the_user_brought_something(self) -> None:
        self.assertEqual(self._plan("my crush texted me today").suggested_topics, ())

    def test_active_subject_comes_from_the_tracked_thread_not_keywords(self) -> None:
        thread = ThreadReference(id="t1", title="Planning a Rishikesh trip", origin="user_started", user_interest="high")
        plan = self._plan("haan", guidance=ThreadGuidance(active=thread))

        self.assertEqual(plan.active_topic, "Planning a Rishikesh trip")
        self.assertIsNone(self._plan("college was boring today").active_topic)

    def test_safety_and_boredom_never_suggest_flirting(self) -> None:
        for allow in (True, False):
            self.assertNotIn("romantic/flirty", safety_module_prompt(allow_mild_adult_humor=allow))
        self.assertIn("never flirt with the user", safety_module_prompt(allow_mild_adult_humor=True))
        self.assertNotIn("romantic", boredom_recovery_prompt(ConversationPlan(current_move="boredom_rescue")))


class ProfileWithoutInterestTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        from api.main import app
        from security.auth import CurrentUser, require_user

        app.dependency_overrides[require_user] = lambda: CurrentUser(id="ff-user", email="ff@example.com")
        self.app = app
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()

    def test_saving_the_profile_no_longer_needs_interested_in(self) -> None:
        save_user_profile("ff-user", "woman", "men", "Asha", 22, "Pune")
        response = self.client.put(
            "/api/me/profile", json={"display_name": "Asha", "age": 23, "gender": "woman", "city": "Pune"}
        )

        self.assertEqual(response.status_code, 200, response.text)
        profile = get_user_profile("ff-user")
        self.assertEqual(profile["age"], 23)
        self.assertEqual(profile["interested_in"], "men")


if __name__ == "__main__":
    unittest.main()
