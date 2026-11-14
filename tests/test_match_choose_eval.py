"""The choosing judge evaluation: made-up people with a planted friend and a planted decoy, the three
tests, and the counts the report shows. The judge is mocked; the real run costs model calls."""

import json
import unittest
from unittest.mock import AsyncMock, patch

from agent.evals.matching.choose_eval import (
    DECOYS, FIXTURE_DECOYS, FIXTURE_FRIENDS, build_cases, evaluate, fixture_build, fixture_people, fixture_person, report, summarise, third_person,
)
from agent.evals.matching.personas import MATCH_PERSONAS

NAMES = {p.name: p.id for p in MATCH_PERSONAS} | {d.name: d.id for d in DECOYS}


def judge_who_knows(*, approve_anyone_alone: bool = False):
    """A judge that ranks the planted friend first and flags the decoy, like the right answer."""

    async def judge(text: str, **_: object) -> dict:
        pack = json.loads(text)
        me = NAMES[pack["person"]["name"]]
        keys = {NAMES[c["name"]]: c["key"] for c in pack["candidates"]}
        friend, decoy = FIXTURE_FRIENDS[me], FIXTURE_DECOYS[me]
        pull = {key: "strong" if who == friend or (approve_anyone_alone and len(keys) == 1 and who != decoy) else "none" for who, key in keys.items()}
        order = sorted(keys.values(), key=lambda key: pull[key] != "strong")
        clash = [{"who": keys[decoy], "mine": "p:1", "theirs": f"{keys[decoy]}:1", "note": "would clash"}] if decoy in keys else []
        best = order[0] if pull[order[0]] == "strong" else None
        return {"pull": pull, "order": order, "best": best, "clash": clash}

    return judge


class FixtureTest(unittest.TestCase):
    def test_persona_text_becomes_notes_about_them(self) -> None:
        self.assertEqual(third_person("You follow football. Your humour is dry; you make fun of yourself."), "They follow football. Their humour is dry; they make fun of themself.")
        person = fixture_person("x", "X", "You are X, 25. You walk. You read. You cook. You run.", sample=2)
        self.assertEqual(person.notes[0].text, "They are X, 25.")
        self.assertEqual(len(person.notes), 3)
        self.assertTrue(all(note.reason_ok for note in person.notes))

    def test_every_person_has_a_friend_a_decoy_and_four_others(self) -> None:
        cases = build_cases(FIXTURE_FRIENDS, FIXTURE_DECOYS)
        self.assertEqual(len(cases), 6)
        for case in cases:
            self.assertEqual(FIXTURE_FRIENDS[case.friend], case.person)
            self.assertIn(case.person, next(d.near for d in DECOYS if d.id == case.decoy))
            self.assertEqual(len(case.others), 4)
            self.assertNotIn(case.friend, case.others)
        self.assertEqual(cases, build_cases(FIXTURE_FRIENDS, FIXTURE_DECOYS))  # seeded: the same on a rerun
        self.assertEqual(set(fixture_people()), set(NAMES.values()))


class EvaluateTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_judge_with_the_right_answers_scores_full_marks(self) -> None:
        cases = build_cases(FIXTURE_FRIENDS, FIXTURE_DECOYS)
        with patch("agent.providers.choose_match", AsyncMock(side_effect=judge_who_knows())):
            results = await evaluate(cases, fixture_build(fixture_people()), rounds=2)
        s = summarise(results, cases)
        self.assertEqual((s["with_friend"]["rounds"], s["with_friend"]["friend_first"], s["with_friend"]["decoy_clash"], s["with_friend"]["decoy_last"]), (12, 12, 12, 12))
        self.assertEqual((s["without_friend"]["said_nobody"], s["without_friend"]["picked_decoy"]), (12, 0))
        self.assertEqual((s["one_at_a_time"]["friend_approved"], s["one_at_a_time"]["decoy_approved"], s["one_at_a_time"]["other_approved"], s["one_at_a_time"]["other_total"]), (6, 0, 0, 12))
        text = report(results, cases)
        self.assertIn("| friend chosen as best | 12/12 |", text)
        self.assertNotIn(" · not ", text)  # reasons and why-nots only when asked

    async def test_a_judge_that_approves_anyone_alone_shows_up_in_the_third_test(self) -> None:
        cases = build_cases(FIXTURE_FRIENDS, FIXTURE_DECOYS)
        with patch("agent.providers.choose_match", AsyncMock(side_effect=judge_who_knows(approve_anyone_alone=True))):
            results = await evaluate(cases, fixture_build(fixture_people()), tests=("one_at_a_time",))
        s = summarise(results, cases)["one_at_a_time"]
        self.assertEqual((s["other_approved"], s["decoy_approved"]), (12, 0))

    async def test_a_failed_call_is_counted_and_left_out(self) -> None:
        cases = build_cases(FIXTURE_FRIENDS, FIXTURE_DECOYS)[:1]
        with patch("agent.providers.choose_match", AsyncMock(side_effect=RuntimeError("down"))):
            results = await evaluate(cases, fixture_build(fixture_people()), tests=("with_friend",), rounds=1)
        s = summarise(results, cases)["with_friend"]
        self.assertEqual((s["rounds"], s["errors"], results[0].error), (0, 1, "RuntimeError"))


if __name__ == "__main__":
    unittest.main()
