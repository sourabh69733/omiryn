"""Friends-first: the companion never steers toward romance or flirting with the user."""

import unittest

from fastapi.testclient import TestClient

from agent.context_engine.contracts.models import ContextQueryIntent
from agent.context_engine.conversation_engine.planning.topic_catalog import (
    COMMON_STARTER_TOPIC_POLICY,
    TOPIC_CATALOG,
    relevant_topics_for_intent,
)
from agent.context_engine.prompt_engine.modules.boredom_recovery import boredom_recovery_prompt
from agent.context_engine.prompt_engine.modules.safety import safety_module_prompt
from agent.context_engine.contracts.models import ConversationPlan
from storage import get_user_profile, reset_db, save_user_profile

ROMANCE_WORDS = ("romantic", "flirt", "intimacy", "dating", "partner attention")


class FriendsFirstPromptTest(unittest.TestCase):
    def test_no_topic_or_policy_steers_to_romance(self) -> None:
        text = " ".join(
            [topic.label.casefold() for topic in TOPIC_CATALOG] + list(COMMON_STARTER_TOPIC_POLICY)
        )
        for word in ROMANCE_WORDS:
            self.assertNotIn(word, text)

    def test_bored_user_gets_friend_topics(self) -> None:
        topics = relevant_topics_for_intent(
            "hmm", ContextQueryIntent(labels=("low_information",), is_low_information=True)
        )
        self.assertTrue(topics)
        self.assertNotIn("relationships", {topic.id for topic in topics})

    def test_relationships_only_when_the_user_raises_them(self) -> None:
        topics = relevant_topics_for_intent("my crush texted me today", ContextQueryIntent())
        self.assertIn("relationships", {topic.id for topic in topics})

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
