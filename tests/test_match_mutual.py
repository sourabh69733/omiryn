"""The two-sided pick: a pair needs both people to call it strong, nobody is in two pairs, and with
MATCH_JUDGE=3 the pool pick, the pair made by hand and readiness all run on match notes."""

import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from agent.matching.choose import Choice, Loaded, Note
from agent.matching.mutual import check_two, closeness, mutual_pick, pair_check, shortlist
from agent.matching.pick import pick_pool
from agent.matching.pool import propose_pair
from agent.matching.readiness import match_readiness
from storage import create_match_pool, join_match_pool, list_match_pairs, reset_db, save_user_profile, set_match_notes


def person(ref: str, name: str, **extra) -> Loaded:
    return Loaded(ref, name, (Note(f"{name} loves long walks and old films.", True, area="loves", note_id="n1"), Note(f"{name} jokes drily.", True, area="humour", note_id="n2")), (), extra.get("vectors", {}), {})


PEOPLE = {ref: person(ref, name) for ref, name in (("ua", "Aman"), ("ub", "Bela"), ("uc", "Chitra"), ("ud", "Dev"))}
NAMES = {p.name: ref for ref, p in PEOPLE.items()}


def judge(likes: dict[str, list[str]], *, alone: dict[str, list[str]] | None = None, clash: dict[str, list[str]] | None = None, fail: set[str] | None = None):
    """A judge that knows who each person finds strong: `likes` when ranking several, `alone` (else
    `likes`) when shown one person; `clash` marks who they could not stand."""

    async def answer(text: str, **_: object) -> dict:
        pack = json.loads(text)
        me = NAMES[pack["person"]["name"]]
        if me in (fail or set()):
            raise RuntimeError("down")
        keys = {NAMES[c["name"]]: c["key"] for c in pack["candidates"]}
        strong = (alone or likes).get(me, []) if len(keys) == 1 and alone is not None else likes.get(me, [])
        clashes = [who for who in (clash or {}).get(me, []) if who in keys]
        pull = {key: "strong" if who in strong and who not in clashes else "some" for who, key in keys.items()}
        order = sorted(keys.values(), key=lambda key: pull[key] != "strong")
        best = order[0] if pull[order[0]] == "strong" else None
        out = {"pull": pull, "order": order, "best": best, "clash": [{"who": keys[who], "mine": "p:1", "theirs": f"{keys[who]}:1", "note": "would clash"} for who in clashes]}
        if best:
            other = next(c["name"] for c in pack["candidates"] if c["key"] == best)
            out["reasons"] = [{"mine": "p:1", "theirs": f"{best}:1", "text": f"{pack['person']['name']} and {other} both love long walks and old films."}]
            out["icebreaker"] = "Which old film first?"
        return out

    return AsyncMock(side_effect=answer)


class MutualPickTest(unittest.IsolatedAsyncioTestCase):
    async def test_two_people_who_pick_each_other_are_a_pair_and_the_rest_wait(self) -> None:
        with patch("agent.providers.choose_match", judge({"ua": ["ub"], "ub": ["ua"]})):
            result = await mutual_pick(PEOPLE, seed=1)
        self.assertEqual([(p.user_a, p.user_b, p.kind) for p in result.pairs], [("ua", "ub", "both_best")])
        self.assertEqual(result.waiting, ["uc", "ud"])
        check = result.pairs[0].check
        self.assertEqual((check["fit"], check["version"], check["mutual"], len(check["reasons"])), ("yes", 3, "both_best", 1))  # the same reason from both sides, told once
        self.assertEqual((check["reasons"][0]["area"], check["reasons"][0]["source"], check["icebreaker"]), ("loves", "note:n1", "Which old film first?"))
        self.assertEqual(check["views"]["ua"], {"place": 1, "pull": "strong"})

    async def test_one_sided_needs_the_other_to_agree_when_shown_alone(self) -> None:
        # Aman's best is Bela. Bela, ranking several, names nobody; shown Aman alone, she says strong.
        with patch("agent.providers.choose_match", judge({"ua": ["ub"]}, alone={"ua": ["ub"], "ub": ["ua"]})):
            agreed = await mutual_pick(PEOPLE, seed=1)
        self.assertEqual([(p.user_a, p.user_b, p.kind) for p in agreed.pairs], [("ua", "ub", "confirmed_back")])
        # Shown alone she still does not: no pair, and the reason is kept for the operator.
        with patch("agent.providers.choose_match", judge({"ua": ["ub"]}, alone={"ua": ["ub"]})):
            refused = await mutual_pick(PEOPLE, seed=1)
        self.assertEqual((refused.pairs, refused.not_taken), ([], [("ua", "ub", "the other side did not call it strong")]))
        self.assertEqual(refused.waiting, ["ua", "ub", "uc", "ud"])

    async def test_a_clash_from_the_other_side_ends_it_without_another_call(self) -> None:
        call = judge({"ua": ["ub"]}, clash={"ub": ["ua"]})
        with patch("agent.providers.choose_match", call):
            result = await mutual_pick(PEOPLE, seed=1)
        self.assertEqual((result.pairs, result.not_taken), ([], [("ua", "ub", "the other side sees a clash")]))
        self.assertEqual(call.await_count, 4 + 1)  # four rankings, Aman's second look at Bela, no check back

    async def test_nobody_is_in_two_pairs_and_picking_each_other_wins(self) -> None:
        # Bela and Chitra pick each other. Aman also wants Bela, and Bela alone would agree.
        with patch("agent.providers.choose_match", judge({"ua": ["ub"], "ub": ["uc"], "uc": ["ub"]}, alone={"ua": ["ub"], "ub": ["uc", "ua"], "uc": ["ub"]})):
            result = await mutual_pick(PEOPLE, seed=1)
        self.assertEqual([(p.user_a, p.user_b, p.kind) for p in result.pairs], [("ub", "uc", "both_best")])
        self.assertIn(("ua", "ub", "one of them was taken by a better pair"), result.not_taken)
        self.assertEqual(result.waiting, ["ua", "ud"])

    async def test_people_who_must_not_be_paired_never_see_each_other_and_a_failed_call_only_loses_that_person(self) -> None:
        call = judge({"ua": ["ub"], "ub": ["ua"], "uc": ["ud"], "ud": ["uc"]}, fail={"ud"})
        with patch("agent.providers.choose_match", call):
            result = await mutual_pick(PEOPLE, lambda a, b: {a, b} != {"ua", "ub"}, seed=1)
        for sent in call.await_args_list:
            pack = json.loads(sent.args[0])
            if pack["person"]["name"] == "Aman":
                self.assertNotIn("Bela", [c["name"] for c in pack["candidates"]])
        self.assertEqual(result.pairs, [])
        self.assertEqual(result.errors, {"ud": "RuntimeError"})
        self.assertIn(("uc", "ud", "the check back failed"), result.not_taken)

    async def test_a_pair_made_by_hand_is_yes_only_when_both_agree(self) -> None:
        a, b = PEOPLE["ua"], PEOPLE["ub"]
        with patch("agent.providers.choose_match", judge({"ua": ["ub"], "ub": ["ua"]})):
            self.assertEqual((await check_two(a, b))["fit"], "yes")
        with patch("agent.providers.choose_match", judge({"ua": ["ub"]})):
            one = await check_two(a, b)
        self.assertEqual((one["fit"], one["reasons"], bool(one["why_not"])), ("maybe", [], True))
        with patch("agent.providers.choose_match", judge({"ua": ["ub"], "ub": ["ua"]}, clash={"ub": ["ua"]})):
            clash = await check_two(a, b)
        self.assertEqual((clash["fit"], clash["clash"]), ("no", {"note": "would clash"}))


class PiecesTest(unittest.TestCase):
    def test_reasons_from_both_sides_are_merged_and_the_same_one_is_told_once(self) -> None:
        def view(me: str, other: str, texts: list[str]) -> Choice:
            return Choice(me, (other,), other, [{"text": t, "mine": f"note:{i}", "theirs": "note:x", "area": "loves"} for i, t in enumerate(texts)], pull={other: "strong"})

        check = pair_check(
            view("ua", "ub", ["Aman and Bela both love long walks.", "Both joke drily."]),
            view("ub", "ua", ["Bela and Aman both love long walks.", "Both want a friend for slow Sundays.", "Both read at night."]),
            a="ua", b="ub", kind="both_best",
        )
        self.assertEqual([r["text"] for r in check["reasons"]], ["Aman and Bela both love long walks.", "Both joke drily.", "Both want a friend for slow Sundays."])

    def test_the_shortlist_keeps_the_closest_in_meaning(self) -> None:
        def vector(x: float, y: float) -> dict:
            return {"provider": "p", "model": "m", "dimensions": 2, "values": [x, y]}

        me = person("me", "Me", vectors={"m1": vector(1.0, 0.0)})
        near = person("near", "Near", vectors={"m1": vector(0.9, 0.1)})
        far = person("far", "Far", vectors={"m1": vector(0.0, 1.0)})
        blank = person("blank", "Blank")
        self.assertGreater(closeness(me, near), closeness(me, far))
        self.assertEqual(closeness(me, blank), 0.0)
        self.assertEqual([p.ref for p in shortlist(me, [far, blank, near], limit=1)], ["near"])
        self.assertEqual([p.ref for p in shortlist(me, [far, blank, near])], ["far", "blank", "near"])  # everyone fits: untouched


def notes(*kinds: str) -> dict:
    return {"version": 1, "covered_upto": None, "messages_seen": 0, "notes": [{"id": f"n{i}", "kind": kind, "text": f"Enjoys long walks and old films ({kind} {i}).", "evidence": [{"conversation_id": "c", "message_index": i}]} for i, kind in enumerate(kinds, start=1)]}


READY_NOTES = ("loves", "loves", "humour", "wants", "gives", "rhythm")


class LiveFlowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.pool = create_match_pool("Baner block A")
        for user_id, name in (("ua", "Aman"), ("ub", "Bela"), ("uc", "Chitra"), ("ud", "Dev")):
            save_user_profile(user_id, "female", "male", display_name=name, city="Pune")
            join_match_pool(user_id, self.pool["join_code"])
            if user_id != "ud":
                set_match_notes(user_id, notes(*READY_NOTES))
        set_match_notes("ud", notes("loves", "humour"))  # too little known

    def test_ready_comes_from_the_notes_only_when_the_switch_is_on(self) -> None:
        self.assertFalse(match_readiness("ua").ready)  # no vibe card: the old rule
        with patch.dict(os.environ, {"MATCH_JUDGE": "3"}):
            ready, thin = match_readiness("ua"), match_readiness("ud")
        self.assertTrue(ready.ready)
        self.assertEqual((ready.blockers, ready.as_dict()["notes"]["notes"]), ((), 6))
        self.assertFalse(thin.ready)
        self.assertIn("2 notes", thin.blockers[0])
        self.assertNotIn("notes", match_readiness("ua").as_dict())

    async def test_the_pool_pick_stores_only_pairs_both_sides_want(self) -> None:
        call = judge({"ua": ["ub"], "ub": ["ua"], "uc": ["ua"]}, alone={"ua": ["ub"], "ub": ["ua"], "uc": ["ua"]})
        with patch.dict(os.environ, {"MATCH_JUDGE": "3"}), patch("agent.providers.choose_match", call):
            proposal = await pick_pool(self.pool["id"], created_by="op")
        self.assertEqual([(c.user_a, c.user_b) for c in proposal.pairs], [("ua", "ub")])
        self.assertEqual(proposal.waiting, ["uc"])  # Dev was never ready, so he is not even waiting
        self.assertEqual(proposal.as_dict()["not_taken"], [{"user_a": "uc", "user_b": "ua", "why": "the other side did not call it strong"}])
        stored = list_match_pairs(self.pool["id"])
        self.assertEqual([(p["status"], p["check"]["version"], p["check"]["mutual"], p["check"]["fit"]) for p in stored], [("proposed", 3, "both_best", "yes")])
        # Nobody was asked about Dev, and Dev was asked about nobody.
        for sent in call.await_args_list:
            pack = json.loads(sent.args[0])
            self.assertNotIn("Dev", [pack["person"]["name"], *[c["name"] for c in pack["candidates"]]])
        # The same week again: the pair is pending, so one ready person is left and that is too few.
        with patch.dict(os.environ, {"MATCH_JUDGE": "3"}), patch("agent.providers.choose_match", call):
            again = await pick_pool(self.pool["id"], created_by="op")
        self.assertEqual((again.pairs, again.waiting, again.busy), ([], ["uc"], ["ua", "ub"]))

    async def test_a_pair_made_by_hand_uses_the_same_judge(self) -> None:
        with patch.dict(os.environ, {"MATCH_JUDGE": "3"}), patch("agent.providers.choose_match", judge({"ua": ["uc"], "uc": ["ua"]})):
            pair = await propose_pair(self.pool["id"], "ua", "uc", created_by="op")
        self.assertEqual((pair["status"], pair["check"]["fit"], len(pair["check"]["reasons"])), ("proposed", "yes", 1))
        with patch.dict(os.environ, {"MATCH_JUDGE": "3"}), patch("agent.providers.choose_match", judge({"ub": ["uc"]})):
            thin = await propose_pair(self.pool["id"], "ub", "uc", created_by="op")
        self.assertEqual((thin["check"]["fit"], thin["check"]["reasons"]), ("maybe", []))


if __name__ == "__main__":
    unittest.main()
