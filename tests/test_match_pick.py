"""The pick: drop what cannot work, order the rest, each ready person once, a group in a thin week,
"one more week" under three ready people; judged pairs are stored as candidates and reused for a
week; pairs with a past are never proposed again."""

import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agent.matching.compatibility import MatchCheck
from agent.matching.pick import Candidate, eligible_pairs, greedy_pairs, pick_pool, propose, rank_candidates, thin_week_group
from api.main import app
from storage import create_match_pool, join_match_pool, list_match_pairs, reset_db, save_match_pair, save_user_profile, update_vibe_card
from test_matching import ready_areas


def _c(a: str, b: str, fit: str = "yes", reasons: int = 2, meet: str = "unknown", clash: bool = False, gaps=(), score: int = 50) -> Candidate:
    return Candidate(f"{a}{b}", a, b, {"fit": fit, "reasons": [{"text": "r"}] * reasons, "meet_fit": {"level": meet}, "clash": {"source": "x"} if clash else None, "score": score}, tuple(gaps))


class PureTest(unittest.TestCase):
    def test_rank_drops_clash_no_and_unknown_and_orders_the_rest(self) -> None:
        kept, dropped = rank_candidates([
            _c("a", "b", clash=True), _c("a", "c", fit="no"), _c("a", "d", fit="unknown"),
            _c("b", "c", fit="maybe", reasons=3), _c("b", "d", reasons=1, meet="easy"), _c("c", "d", reasons=2, meet="awkward"), _c("a", "e", reasons=2, gaps=("hours",)),
        ])
        self.assertEqual([why for _, why in dropped], ["clash", "fit no", "too little to compare"])
        self.assertEqual([c.pair_id for c in kept], ["ae", "cd", "bd", "bc"])  # yes before maybe; more reasons; awkward last among equals

    def test_greedy_takes_each_person_once(self) -> None:
        picked = greedy_pairs([_c("a", "b"), _c("a", "c"), _c("c", "d"), _c("b", "d")])
        self.assertEqual([c.pair_id for c in picked], ["ab", "cd"])

    def test_group_needs_three_linked_people(self) -> None:
        kept = [_c("x", "y"), _c("y", "z"), _c("x", "q")]
        self.assertEqual(sorted(thin_week_group(["x", "y", "z", "q", "w"], kept)), ["q", "x", "y", "z"])
        self.assertEqual(thin_week_group(["x", "y", "w"], kept), [])

    def test_propose_end_to_end_and_one_more_week(self) -> None:
        ready = ["a", "b", "c", "d", "e", "f", "g"]
        candidates = [_c("a", "b"), _c("c", "d", fit="maybe"), _c("e", "f", clash=True), _c("e", "g", fit="maybe", reasons=1), _c("f", "g", fit="maybe", reasons=1), _c("a", "g")]
        proposal = propose(ready, candidates)
        self.assertEqual([c.pair_id for c in proposal.pairs], ["ab", "cd", "eg"])
        self.assertEqual(proposal.waiting, ["f"])
        self.assertEqual(proposal.group, [])
        self.assertEqual([why for _, why in proposal.dropped], ["clash"])
        thin = propose(["a", "b"], [_c("a", "b")])
        self.assertEqual((thin.pairs, thin.waiting), ([], ["a", "b"]))
        self.assertEqual(proposal.as_dict()["pairs"][0]["fit"], "yes")

    def test_eligible_pairs_skip_any_past_and_reuse_a_fresh_candidate(self) -> None:
        history = [
            {"id": "p1", "user_a": "a", "user_b": "b", "status": "declined", "plan": None, "check": {}, "updated_at": "2026-11-06T10:00:00+00:00"},
            {"id": "p2", "user_a": "a", "user_b": "c", "status": "candidate", "plan": None, "check": {"fit": "yes"}, "updated_at": "2099-01-01T10:00:00+00:00"},
            {"id": "p3", "user_a": "b", "user_b": "c", "status": "candidate", "plan": None, "check": {"fit": "yes"}, "updated_at": "2020-01-01T10:00:00+00:00"},
        ]
        pairs = eligible_pairs(["a", "b", "c"], history)
        self.assertEqual([(a, b, fresh["id"] if fresh else None) for a, b, fresh in pairs], [("a", "c", "p2"), ("b", "c", None)])


class PickPoolTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.pool = create_match_pool("Baner block A")
        for user_id, name in (("ua", "Aman"), ("ub", "Bela"), ("uc", "Chitra"), ("ud", "Dev")):
            save_user_profile(user_id, "female", "male", display_name=name, city="Pune")
            update_vibe_card(user_id, ready_areas())
            join_match_pool(user_id, self.pool["join_code"])

    async def test_pick_judges_stores_candidates_and_marks_the_picked_pairs(self) -> None:
        def check(fit: str) -> MatchCheck:
            return MatchCheck(fit, 50, ("humor",), [{"source": "area:humor", "text": "r"}] if fit == "yes" else [])

        judge = AsyncMock(side_effect=lambda a, b: check("yes" if {a, b} in ({"ua", "ub"}, {"uc", "ud"}) else "maybe"))
        with patch("agent.matching.readiness.match_readiness", side_effect=lambda u: type("R", (), {"ready": True, "facts_known": {}})()), patch("agent.matching.compatibility.check_compatibility", judge):
            proposal = await pick_pool(self.pool["id"], created_by="op")
        self.assertEqual(judge.await_count, 6)
        self.assertEqual(sorted(c.users for c in proposal.pairs), sorted([frozenset({"ua", "ub"}), frozenset({"uc", "ud"})]))
        statuses = sorted(pair["status"] for pair in list_match_pairs(self.pool["id"]))
        self.assertEqual(statuses, ["candidate"] * 4 + ["proposed"] * 2)
        # A second pick the same week: everyone has a pair pending, so nobody is picked or judged again.
        judge.reset_mock()
        with patch("agent.matching.readiness.match_readiness", side_effect=lambda u: type("R", (), {"ready": True, "facts_known": {}})()), patch("agent.matching.compatibility.check_compatibility", judge):
            again = await pick_pool(self.pool["id"], created_by="op")
        judge.assert_not_awaited()
        self.assertEqual((again.pairs, again.waiting, again.busy), ([], [], ["ua", "ub", "uc", "ud"]))
        self.assertEqual(again.as_dict()["busy"], ["ua", "ub", "uc", "ud"])

    def test_operator_endpoint(self) -> None:
        with patch.dict(os.environ, {"AUTH_REQUIRED": "false", "ADMIN_ALLOW_UNAUTHENTICATED_DEV": "true", "AGENT_PROVIDER": "mock"}):
            client = TestClient(app)
            self.assertEqual(client.post("/api/admin/pools/nope/pick").status_code, 404)
            with patch("agent.matching.readiness.match_readiness", side_effect=lambda u: type("R", (), {"ready": u != "ud", "facts_known": {}})()):
                body = client.post(f"/api/admin/pools/{self.pool['id']}/pick").json()
            # The mock provider returns {} so every judgement is "maybe" with no reasons: still proposable.
            self.assertEqual(body["judged"], 3)
            self.assertEqual(len(body["pairs"]), 1)
            self.assertEqual(len(body["waiting"]), 1)


if __name__ == "__main__":
    unittest.main()
