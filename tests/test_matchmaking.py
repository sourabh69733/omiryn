import unittest

from matching import (
    AgePreference,
    Dealbreaker,
    MatchProfile,
    evaluate_hard_filters,
    score_match,
)


def make_aarav() -> MatchProfile:
    return MatchProfile(
        id="user-a",
        age=29,
        age_preference=AgePreference(min=26, max=32),
        relationship_intent="long_term",
        values=["family", "ambition", "emotional_stability"],
        lifestyle=["fitness", "travel", "balanced_work"],
        communication_style="direct",
        religion_importance="medium",
        family_involvement="medium",
        children_preference="wants_children",
        city="Bengaluru",
        dealbreakers=[Dealbreaker(type="smoking", severity="hard")],
        attributes=["vegetarian"],
    )


def make_meera() -> MatchProfile:
    return MatchProfile(
        id="user-b",
        age=28,
        age_preference=AgePreference(min=28, max=34),
        relationship_intent="marriage",
        values=["family", "ambition", "kindness"],
        lifestyle=["fitness", "travel", "early_riser"],
        communication_style="direct",
        religion_importance="medium",
        family_involvement="medium",
        children_preference="wants_children",
        city="Bengaluru",
        dealbreakers=[Dealbreaker(type="heavy_drinking", severity="hard")],
        attributes=["non_smoker"],
    )


class MatchmakingScorerTest(unittest.TestCase):
    def test_hard_filters_pass_for_mutually_compatible_serious_relationship_users(self) -> None:
        self.assertIs(evaluate_hard_filters(make_aarav(), make_meera()).pass_, True)

    def test_matching_scorer_returns_a_strong_candidate_for_compatible_users(self) -> None:
        result = score_match(make_aarav(), make_meera())

        self.assertEqual(result.decision, "strong_candidate")
        self.assertGreaterEqual(result.score, 70)
        self.assertIn("Strong areas", result.explanation)

    def test_hard_dealbreakers_reject_a_candidate(self) -> None:
        smoker = MatchProfile(
            **{
                **make_meera().__dict__,
                "id": "user-c",
                "attributes": ["smoking"],
            }
        )

        result = score_match(make_aarav(), smoker)

        self.assertEqual(result.decision, "reject")
        self.assertEqual(result.score, 0)

    def test_age_preferences_must_work_in_both_directions(self) -> None:
        outside_preference = MatchProfile(
            **{
                **make_meera().__dict__,
                "age": 35,
            }
        )

        result = score_match(make_aarav(), outside_preference)

        self.assertEqual(result.decision, "reject")
        self.assertIn("Age preference", result.explanation)


if __name__ == "__main__":
    unittest.main()
