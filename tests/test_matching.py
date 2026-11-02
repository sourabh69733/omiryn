"""Matching: readiness (is this user known well enough) and compatibility (how two would get along)."""

import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agent.matching import check_compatibility, comparable_areas, compatibility_score, readiness_from, validate_match_reasons
from agent.matching.compatibility import match_reasons_input, shareable_areas
from agent.shared.vibe import BASIC_AREA_IDS, DEEPER_AREA_IDS, PRIVATE_AREA_IDS
from api.main import app, current_user
from security.auth import CurrentUser
from storage import reset_db, save_user_profile, set_private_matching_consent, update_vibe_card


def line(text: str, days: int = 2, chat: str = "c") -> dict:
    return {"text": text, "evidence": [{"conversation_id": chat, "message_index": i, "sent_at": f"2026-09-{10 + i:02d}T10:00:00+00:00"} for i in range(days)]}


def ready_areas(**overrides) -> dict:
    areas = {a: line(f"{a} line about them") for a in BASIC_AREA_IDS}
    for a in DEEPER_AREA_IDS[:3]:
        areas[a] = line(f"{a} line about them")
    areas.update(overrides)
    return areas


def memory(statement: str) -> dict:
    return {"status": "active", "statement": statement, "key": "", "value": statement, "purposes": ["profile"]}


class ReadinessTest(unittest.TestCase):
    def test_ready_needs_the_milestone_and_the_required_facts(self) -> None:
        memories = [memory("Lives in Baner, Pune, near the highway."), memory("Free most weekday evenings after 7 and on Sundays.")]
        result = readiness_from(ready_areas(), memories, {})
        self.assertTrue(result.ready, result.blockers)
        self.assertEqual(result.milestone, "ready_to_match")
        self.assertEqual(set(result.facts_known), {"area", "free_time"})
        self.assertEqual(result.facts_missing, ("food", "budget"))

    def test_missing_required_facts_block_with_plain_reasons(self) -> None:
        result = readiness_from(ready_areas(), [memory("Loves spicy food, strictly vegetarian.")], {})
        self.assertFalse(result.ready)
        self.assertEqual(result.blockers, ("not known yet: area, free time",))
        self.assertIn("food", result.facts_known)

    def test_a_thin_card_blocks_even_with_facts(self) -> None:
        areas = {a: line(f"{a} line", days=1) for a in BASIC_AREA_IDS}
        result = readiness_from(areas, [memory("Lives in Kothrud."), memory("Free on weekends.")], {})
        self.assertFalse(result.ready)
        self.assertEqual(result.milestone, "first_impressions")
        self.assertTrue(result.blockers[0].startswith("vibe card is at"))
        self.assertEqual(len(result.mentioned_areas), len(BASIC_AREA_IDS))

    def test_the_profile_city_stands_in_for_the_area(self) -> None:
        result = readiness_from(ready_areas(), [memory("Free on weekends and Saturday mornings for a walk.")], {"city": "Pune"})
        self.assertEqual(result.facts_known["area"], "city: Pune (area not known)")
        self.assertTrue(result.ready)

    def test_the_api_returns_it(self) -> None:
        reset_db()
        app.dependency_overrides.clear()

        async def signed_in() -> CurrentUser:
            return CurrentUser(id="ready-user", email="r@example.com", display_name="Ready")

        app.dependency_overrides[current_user] = signed_in
        update_vibe_card("ready-user", {a: ready_areas()[a] for a in ready_areas()})
        with patch.dict(os.environ, {"AUTH_REQUIRED": "false"}):
            body = TestClient(app).get("/api/me/match-readiness").json()
        app.dependency_overrides.clear()
        self.assertEqual(body["milestone"], "ready_to_match")
        self.assertFalse(body["ready"])
        self.assertEqual(body["facts"]["missing"], ["area", "free_time", "food", "budget"])


class CompatibilityTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.a = ready_areas(humor=line("Laughs at dry, deadpan jokes and bad puns."), interests=line("Treks every month and reads sci-fi."), values=line("Thinks caste should not matter at all."))
        self.b = ready_areas(humor=line("Deadpan humour, loves a terrible pun."), interests=line("Weekend treks in the Sahyadris, reads fantasy."), values=line("Religious, prays daily."))

    def test_private_areas_compare_only_with_both_consents_and_are_never_shareable(self) -> None:
        without = comparable_areas(self.a, self.b, both_private_allowed=False)
        with_consent = comparable_areas(self.a, self.b, both_private_allowed=True)
        self.assertNotIn("values", without)
        self.assertIn("values", with_consent)
        self.assertTrue(set(PRIVATE_AREA_IDS).isdisjoint(shareable_areas(with_consent)))
        self.assertGreaterEqual(len(without), 3)

    def test_the_score_rewards_coverage_and_shared_lines(self) -> None:
        comparable = comparable_areas(self.a, self.b, both_private_allowed=False)
        alike = compatibility_score(self.a, self.b, comparable)
        stranger = {a: line("Something else entirely about cars.") for a in comparable}
        apart = compatibility_score(self.a, stranger, comparable)
        self.assertGreater(alike, apart)
        self.assertEqual(compatibility_score(self.a, self.b, ()), 0)

    def test_reasons_are_kept_only_for_shareable_areas(self) -> None:
        shareable = ("humor", "interests", "social_energy")
        raw = {"fit": "yes", "reasons": [
            {"area": "humor", "text": "Both laugh at the same bad puns."},
            {"area": "values", "text": "Both think caste should not matter."},
            {"area": "humor", "text": "duplicate area"},
            {"area": "interests", "text": "Both trek."}, {"area": "social_energy", "text": "x"}, {"area": "daily_life", "text": "not comparable"},
        ], "difference": {"area": "values", "text": "private difference"}, "icebreaker": "  Worst pun you know?  "}
        checked = validate_match_reasons(raw, shareable)
        self.assertEqual([r["area"] for r in checked["reasons"]], ["humor", "interests", "social_energy"])
        self.assertIsNone(checked["difference"])
        self.assertEqual(checked["icebreaker"], "Worst pun you know?")
        self.assertEqual(validate_match_reasons({"fit": "yes", "reasons": []}, shareable)["fit"], "maybe")
        self.assertEqual(validate_match_reasons("garbage", shareable)["fit"], "maybe")

    async def test_check_loads_cards_and_asks_the_model_only_with_enough_in_common(self) -> None:
        reset_db()
        save_user_profile("ua", "male", "female", display_name="Aman Verma")
        save_user_profile("ub", "female", "male", display_name="Bela Rao")
        update_vibe_card("ua", self.a)
        update_vibe_card("ub", self.b)
        set_private_matching_consent("ua", True)
        writer = AsyncMock(return_value={"fit": "yes", "reasons": [{"area": "humor", "text": "Aman and Bela both love a bad pun."}, {"area": "values", "text": "leaks"}], "difference": {"area": "interests", "text": "Sci-fi versus fantasy, both read."}})
        with patch("agent.providers.write_match_reasons", writer):
            result = await check_compatibility("ua", "ub")
        self.assertEqual(result.fit, "yes")
        self.assertEqual([r["area"] for r in result.reasons], ["humor"])
        self.assertEqual(result.difference["area"], "interests")
        sent = json.loads(writer.await_args.args[0])
        self.assertEqual((sent["a"]["name"], sent["b"]["name"]), ("Aman", "Bela"))
        self.assertNotIn("values", sent["comparable"])  # only one side consented
        # Too little in common: no model call.
        update_vibe_card("uc", {"humor": line("Dry humour.")})
        writer.reset_mock()
        with patch("agent.providers.write_match_reasons", writer):
            thin = await check_compatibility("ua", "uc")
        self.assertEqual(thin.fit, "unknown")
        writer.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
