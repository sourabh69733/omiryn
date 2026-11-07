"""Judge v2: the evidence pack code builds (vibe lines, touchpoints, style lines, meet facts) and the
checks on what comes back. A reason survives only with an allowed source and words from it; a clash
may name any comparable source, private ones included; everything else is bounded and cleaned."""

import json
import unittest
from unittest.mock import AsyncMock, patch

import storage
from agent.matching.compatibility import allowed_sources, check_compatibility, evidence_pack, grounded, validate_match_judgement
from agent.shared.vibe import BASIC_AREA_IDS


def line(text: str) -> dict:
    return {"text": text, "evidence": [{"conversation_id": "c", "message_index": i, "sent_at": f"2026-09-{10 + i:02d}T10:00:00+00:00"} for i in range(2)]}


AREAS_A = {a: line(f"{a} line") for a in BASIC_AREA_IDS} | {
    "humor": line("Laughs at dry, deadpan jokes and bad puns."),
    "interests": line("Walks the Fergusson loop most evenings and reads sci-fi."),
    "deal_breakers": line("Cannot stand people who cancel at the last minute."),
}
AREAS_B = {a: line(f"{a} line") for a in BASIC_AREA_IDS} | {
    "humor": line("Deadpan humour, loves a terrible pun."),
    "interests": line("Tries to walk 6 km every evening, reads fantasy."),
    "deal_breakers": line("Hates being lectured."),
}
COMPARABLE = tuple(BASIC_AREA_IDS) + ("deal_breakers",)
POINTS = [
    {"a": "Fasts on Thursdays", "b": "Cooks non-veg on weekends", "reason_ok": True},
    {"a": "Broke with her college group over money", "b": "Lent money to a friend, never got it back", "reason_ok": False},
]


class PackTest(unittest.TestCase):
    def test_the_pack_numbers_touchpoints_and_carries_style_and_meet(self) -> None:
        pack = json.loads(evidence_pack("Priya", AREAS_A, "Rohan", AREAS_B, COMPARABLE, touchpoints=POINTS, style_lines=["both write mostly Hinglish"], meet_a={"area": "Baner"}, meet_b={}))
        self.assertEqual([p["n"] for p in pack["touchpoints"]], [1, 2])
        self.assertEqual(pack["touchpoints"][1]["reason_ok"], False)
        self.assertNotIn("deal_breakers", pack["shareable"])
        self.assertIn("deal_breakers", pack["comparable"])
        self.assertEqual(pack["style"], ["both write mostly Hinglish"])
        self.assertEqual(pack["meet"]["a"], {"area": "Baner"})

    def test_sources_a_reason_and_a_clash_may_name(self) -> None:
        reason, clash = allowed_sources(COMPARABLE, POINTS, AREAS_A, AREAS_B)
        self.assertIn("area:humor", reason)
        self.assertNotIn("area:deal_breakers", reason)
        self.assertIn("touchpoint:1", reason)
        self.assertNotIn("touchpoint:2", reason)
        self.assertIn("area:deal_breakers", clash)
        self.assertIn("touchpoint:2", clash)

    def test_grounding_uses_the_source_words_with_endings_dropped(self) -> None:
        source = "Laughs at dry, deadpan jokes and bad puns. Deadpan humour, loves a terrible pun."
        self.assertTrue(grounded("Priya and Rohan both love a bad pun.", source))
        self.assertFalse(grounded("Priya and Rohan both adore cricket on Sundays.", source))
        self.assertTrue(grounded("Deadpan, both.", source))


class ValidateTest(unittest.TestCase):
    def test_keeps_grounded_allowed_reasons_and_drops_the_rest(self) -> None:
        raw = {
            "fit": "yes",
            "reasons": [
                {"source": "area:humor", "text": "Priya and Rohan both love deadpan jokes and a bad pun."},
                {"source": "area:deal_breakers", "text": "Both cannot stand being lectured."},  # private
                {"source": "touchpoint:2", "text": "Both lost friends over money."},  # reason_ok false
                {"source": "touchpoint:1", "text": "Priya fasts on Thursdays and Rohan cooks non-veg on weekends, both fine with it."},
                {"source": "area:interests", "text": "They both play chess online."},  # not in the source words
                {"source": "area:humor", "text": "deadpan again, both"},  # duplicate source
            ],
            "difference": {"source": "area:interests", "text": "Sci-fi for Priya, fantasy for Rohan; both read."},
            "icebreaker": "  Worst pun you know?  ",
            "clash": {"source": "area:deal_breakers", "note": "Rohan cancelled on his flatmate twice; Priya cannot stand that."},
            "meet_fit": {"level": "Easy", "line": "both free weekday evenings"},
            "chemistry": "Both quiet-leaning; Rohan would carry the first ten minutes.",
        }
        checked = validate_match_judgement(raw, COMPARABLE, POINTS, AREAS_A, AREAS_B)
        self.assertEqual([r["source"] for r in checked["reasons"]], ["area:humor", "touchpoint:1"])
        self.assertEqual(checked["reasons"][0]["area"], "humor")
        self.assertNotIn("area", checked["reasons"][1])
        self.assertEqual(checked["difference"]["area"], "interests")
        self.assertEqual(checked["icebreaker"], "Worst pun you know?")
        self.assertEqual(checked["clash"]["source"], "area:deal_breakers")
        self.assertEqual(checked["meet_fit"], {"level": "easy", "line": "both free weekday evenings"})
        self.assertTrue(checked["chemistry"].startswith("Both quiet"))

    def test_bad_shapes_fall_back_safely(self) -> None:
        checked = validate_match_judgement({"fit": "YES", "reasons": [{"source": "area:humor", "text": "They both play chess."}], "clash": {"source": "area:values", "note": "x"}, "meet_fit": {"level": "great"}}, COMPARABLE, POINTS, AREAS_A, AREAS_B)
        self.assertEqual((checked["fit"], checked["reasons"], checked["clash"], checked["meet_fit"]), ("maybe", [], None, None))
        self.assertEqual(validate_match_judgement("garbage", COMPARABLE, [], AREAS_A, AREAS_B)["fit"], "maybe")


class CheckTest(unittest.IsolatedAsyncioTestCase):
    async def test_the_check_sends_touchpoints_style_and_meet_facts_and_keeps_them_on_the_result(self) -> None:
        storage.reset_db()
        storage.save_user_profile("ua", "female", "male", display_name="Priya Nair")
        storage.save_user_profile("ub", "male", "female", display_name="Rohan Shah")
        storage.update_vibe_card("ua", AREAS_A)
        storage.update_vibe_card("ub", AREAS_B)
        judge = AsyncMock(return_value={"fit": "yes", "reasons": [{"source": "area:humor", "text": "Priya and Rohan both love a bad pun."}], "chemistry": "Would flow."})
        with patch("agent.providers.judge_match", judge), patch(
            "agent.matching.touchpoints.pair_touchpoints", return_value=[]
        ), patch("agent.matching.style.pair_style_lines", return_value=["both write mostly Hinglish"]):
            result = await check_compatibility("ua", "ub")
        sent = json.loads(judge.await_args.args[0])
        self.assertEqual(sent["style"], ["both write mostly Hinglish"])
        self.assertEqual({sent["a"]["name"], sent["b"]["name"]}, {"Priya", "Rohan"})
        self.assertEqual(result.fit, "yes")
        self.assertEqual(result.chemistry, "Would flow.")
        self.assertEqual(result.style_lines, ["both write mostly Hinglish"])
        self.assertEqual(result.as_dict()["version"], 2)


if __name__ == "__main__":
    unittest.main()
