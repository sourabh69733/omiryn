import unittest

from agent.memory_engine.data_points import normalize_data_point
from agent.memory_engine.profile_facts import extract_profile_facts_from_message


def _fact_keys(message: str) -> set[tuple[str, str]]:
    return {
        (fact["category"], fact["key"])
        for fact in extract_profile_facts_from_message("user-a", "conversation-a", message, 0)
    }


class DataPointExtractionSafetyTest(unittest.TestCase):
    def test_negated_relationship_intent_is_not_saved_as_positive_fact(self) -> None:
        self.assertNotIn(
            ("dating_intent", "relationship_intent"),
            _fact_keys("I am not looking for marriage right now."),
        )
        self.assertNotIn(
            ("dating_intent", "relationship_intent"),
            _fact_keys("I don't want casual dating, I want serious only."),
        )

    def test_hinglish_negated_relationship_intent_is_not_saved(self) -> None:
        self.assertNotIn(
            ("dating_intent", "relationship_intent"),
            _fact_keys("shaadi abhi nahi chahiye."),
        )
        self.assertNotIn(
            ("dating_intent", "relationship_intent"),
            _fact_keys("mujhe casual nahi chahiye."),
        )

    def test_third_person_relationship_or_lifestyle_signal_is_not_user_fact(self) -> None:
        self.assertNotIn(
            ("dating_intent", "relationship_intent"),
            _fact_keys("My ex wanted marriage, I am not ready for it."),
        )
        self.assertNotIn(
            ("dealbreakers", "smoking"),
            _fact_keys("My friend has a smoking habit and I hate that about him."),
        )

    def test_negated_value_and_lifestyle_are_not_saved_as_positive_facts(self) -> None:
        self.assertNotIn(
            ("values", "family"),
            _fact_keys("I don't value family involvement in dating decisions."),
        )
        self.assertNotIn(
            ("lifestyle", "vegetarian"),
            _fact_keys("I am not vegetarian, but my parents are veg."),
        )

    def test_location_prefers_owned_city_over_temporary_visit(self) -> None:
        facts = extract_profile_facts_from_message(
            "user-a",
            "conversation-a",
            "I visited Delhi once for work, but I live in Pune.",
            0,
        )

        location_facts = [fact for fact in facts if fact["category"] == "location"]
        self.assertEqual(len(location_facts), 1)
        self.assertEqual(location_facts[0]["value"]["city"], "Pune")
        self.assertEqual(location_facts[0]["fact_type"], "profile_fact")
        self.assertFalse(location_facts[0]["used_for_matching"])

    def test_food_preference_is_matching_fact_not_profile_fact(self) -> None:
        facts = extract_profile_facts_from_message(
            "user-a",
            "conversation-a",
            "I love spicy food, teekha food is my thing.",
            0,
        )

        spicy_facts = [fact for fact in facts if fact["category"] == "food_preferences"]
        self.assertEqual(len(spicy_facts), 1)
        self.assertEqual(spicy_facts[0]["fact_type"], "matching_fact")
        self.assertTrue(spicy_facts[0]["used_for_matching"])

    def test_normalizer_classifies_profile_and_matching_facts(self) -> None:
        location = normalize_data_point(
            {
                "user_id": "user-a",
                "category": "location",
                "key": "city",
                "label": "Lives in Pune",
                "value": {"city": "Pune"},
            }
        )
        spicy = normalize_data_point(
            {
                "user_id": "user-a",
                "category": "food_preferences",
                "key": "spicy_food",
                "label": "Prefers spicy food",
                "value": {"kind": "spicy_food"},
            }
        )

        self.assertEqual(location["fact_type"], "profile_fact")
        self.assertEqual(spicy["fact_type"], "matching_fact")
        self.assertEqual(location["confidence_state"], "active")
        self.assertEqual(spicy["confidence_state"], "active")
