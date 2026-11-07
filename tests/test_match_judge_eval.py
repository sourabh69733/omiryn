"""The judge evaluation: known friend pairs and seeded random pairs, judged four ways, summed up as
yes rates and a separation per run; a thin pair is an error, not a verdict."""

import json
import unittest
from unittest.mock import AsyncMock, patch

import storage
from agent.evals.matching.judge_eval import RUNS, evaluate, pick_pairs, report
from test_matching import line, ready_areas

FRIENDS = {frozenset(("Aman", "Bela"))}


async def _judge(text: str, **_: object) -> dict:
    """Says yes to the known friends by name, maybe to everyone else; reasons use the lines' words."""
    pack = json.loads(text)
    names = frozenset((pack["a"]["name"], pack["b"]["name"]))
    fit = "yes" if names in FRIENDS else "maybe"
    return {"fit": fit, "reasons": [{"area": "humor", "source": "area:humor", "text": "Both share the humor line about them."}], "clash": None}


class PickPairsTest(unittest.TestCase):
    def test_known_first_then_seeded_random_pairs_without_the_known_ones(self) -> None:
        pairs = pick_pairs([("a", "b")], ["a", "b", "c", "d"], random_pairs=2, seed=1)
        self.assertEqual(pairs[0], ("a", "b", True))
        self.assertEqual(len(pairs), 3)
        self.assertTrue(all(not known and frozenset((x, y)) != frozenset(("a", "b")) for x, y, known in pairs[1:]))
        self.assertEqual(pairs, pick_pairs([("a", "b")], ["a", "b", "c", "d"], random_pairs=2, seed=1))


class EvaluateTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        storage.reset_db()
        for user_id, name in (("ua", "Aman Verma"), ("ub", "Bela Rao"), ("uc", "Chitra Das"), ("ud", "Dev Iyer")):
            storage.save_user_profile(user_id, "female", "male", display_name=name)
            storage.update_vibe_card(user_id, ready_areas())
        storage.save_user_profile("ue", "male", "female", display_name="Esha Thin")
        storage.update_vibe_card("ue", {"humor": line("Dry.")})

    async def test_runs_sum_up_known_and_random_yes_rates(self) -> None:
        pairs = pick_pairs([("ua", "ub")], ["ua", "ub", "uc", "ud"], random_pairs=2)
        with patch("agent.providers.judge_match", AsyncMock(side_effect=_judge)), patch("agent.providers.write_match_reasons", AsyncMock(side_effect=_judge)):
            verdicts, summaries = await evaluate(pairs)
        self.assertEqual([s.run for s in summaries], list(RUNS))
        for summary in summaries:
            self.assertEqual((summary.known_yes, summary.known_total, summary.random_yes, summary.random_total), (1, 1, 0, 2))
            self.assertEqual(summary.separation, 1.0)
        self.assertEqual(len(verdicts), 3 * len(RUNS))
        text = report(verdicts, summaries, show_reasons=True)
        self.assertIn("| v2_all | 1/1 (100%) | 0/2 (0%) | +1.00 | 0 |", text)
        self.assertIn("Best separation", text)
        self.assertIn("ua + ub | yes | yes | yes | yes | yes |", text)
        self.assertIn("Both share the humor line", text)
        self.assertNotIn("humor line", report(verdicts, summaries))

    async def test_a_thin_card_is_an_error_and_a_failed_call_is_counted(self) -> None:
        pairs = [("ua", "ue", True), ("ua", "uc", False)]
        with patch("agent.providers.judge_match", AsyncMock(side_effect=RuntimeError("down"))), patch("agent.providers.write_match_reasons", AsyncMock(side_effect=RuntimeError("down"))):
            verdicts, summaries = await evaluate(pairs, runs=("v2_all",))
        self.assertEqual([v.fit for v in verdicts], ["unknown", "error"])
        self.assertEqual((summaries[0].errors, summaries[0].known_total, summaries[0].random_total), (2, 0, 0))
        self.assertIn("(RuntimeError)", report(verdicts, summaries))


if __name__ == "__main__":
    unittest.main()
