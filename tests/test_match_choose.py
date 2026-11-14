"""Judge v3, the choosing judge: the pack code builds from notes, the checks on what comes back, and
the second look that has to agree before anyone is best."""

import json
import random
import unittest
from unittest.mock import AsyncMock, patch

from agent.matching.choose import Loaded, Note, Person, choose_among, choose_pack, notes_toward, validate_choice

ME = Person("u-me", "Aarav", (
    Note("Dry, sarcastic humour; sends memes instead of good mornings.", True, area="humor"),
    Note("Follows the Premier League and plays FIFA at night.", True),
    Note("Cannot stand people who cancel at the last minute.", False, area="deal_breakers"),
    Note("Nearly failed second year and a friend dragged them through it.", False),
))
KABIR = Person("u-kabir", "Kabir", (
    Note("Sarcastic and dark humour, makes fun of himself first.", True, area="humor"),
    Note("Follows football and plays FIFA and PUBG at night.", True),
))
VIKRAM = Person("u-vikram", "Vikram", (
    Note("Follows the Premier League and plays FIFA at night.", True),
    Note("Says yes to every plan and drops out of half of them on the day.", True),
))
MEERA = Person("u-meera", "Meera", (Note("Treks one weekend a month and reads fiction.", True),))


def pack_of(*candidates: Person):
    return choose_pack(ME, list(candidates), style={"u-kabir": ["both write mostly Hinglish"]})


class PackTest(unittest.TestCase):
    def test_notes_are_numbered_per_person_and_candidates_get_neutral_keys(self) -> None:
        text, index = pack_of(KABIR, VIKRAM)
        pack = json.loads(text)
        self.assertEqual([n["id"] for n in pack["person"]["notes"]], ["p:1", "p:2", "p:3", "p:4"])
        self.assertEqual(pack["person"]["notes"][0]["area"], "humor")
        self.assertNotIn("area", pack["person"]["notes"][1])
        self.assertEqual([(c["key"], c["name"]) for c in pack["candidates"]], [("c1", "Kabir"), ("c2", "Vikram")])
        self.assertEqual(pack["candidates"][0]["style"], ["both write mostly Hinglish"])
        self.assertEqual(index["keys"], {"c1": "u-kabir", "c2": "u-vikram"})
        # No user id reaches the judge.
        self.assertNotIn("u-kabir", text)


class ValidateTest(unittest.TestCase):
    def setUp(self) -> None:
        _, self.index = pack_of(KABIR, VIKRAM, MEERA)

    def test_a_strong_first_pick_with_grounded_reasons_is_best(self) -> None:
        checked = validate_choice({
            "pull": {"c1": "strong", "c2": "none", "c3": "none"},
            "order": ["c1", "c3", "c2"], "best": "c1",
            "reasons": [
                {"mine": "p:1", "theirs": "c1:1", "text": "Aarav and Kabir both have a sarcastic humour."},
                {"mine": "p:2", "theirs": "c1:2", "text": "Both play FIFA at night."},
            ],
            "icebreaker": "Arsenal or United, who suffers more?", "chemistry": "It would flow.",
            "why_not": {"c3": "Different rhythm.", "c1": "ignored for the best", "zz": "unknown key"},
        }, self.index)
        self.assertEqual((checked["best"], checked["order"]), ("c1", ["c1", "c3", "c2"]))
        self.assertEqual(len(checked["reasons"]), 2)
        self.assertEqual(checked["why_not"], {"c3": "Different rhythm."})
        self.assertTrue(checked["complete"])

    def test_reasons_need_allowed_notes_from_both_people_and_words_from_both(self) -> None:
        checked = validate_choice({
            "pull": {"c1": "strong"}, "order": ["c1"], "best": "c1",
            "reasons": [
                {"mine": "p:3", "theirs": "c1:1", "text": "Kabir is sarcastic and never cancels."},  # p:3 may not back a reason
                {"mine": "p:1", "theirs": "c2:1", "text": "Sarcastic humour and the Premier League."},  # not the best candidate's note
                {"mine": "p:1", "theirs": "c1:2", "text": "Kabir plays FIFA and PUBG at night."},  # nothing from Aarav's note
                {"mine": "p:9", "theirs": "c1:1", "text": "Made up."},
                {"mine": "p:2", "theirs": "c1:2", "text": "Both play FIFA at night."},
                {"mine": "p:2", "theirs": "c1:1", "text": "FIFA and sarcastic humour."},  # p:2 already used
            ],
        }, self.index)
        self.assertEqual(checked["reasons"], [{"mine": "p:2", "theirs": "c1:2", "text": "Both play FIFA at night."}])

    def test_a_clash_goes_last_and_is_never_best(self) -> None:
        checked = validate_choice({
            "pull": {"c1": "some", "c2": "strong", "c3": "none"},
            "order": ["c2", "c1", "c3"], "best": "c2",
            "clash": [
                {"who": "c2", "mine": "p:3", "theirs": "c2:2", "note": "Aarav cannot stand cancelling; Vikram drops out on the day."},
                {"who": "c3", "note": "no notes named, so it does not count"},
            ],
        }, self.index)
        self.assertEqual(checked["order"], ["c1", "c3", "c2"])
        self.assertIsNone(checked["best"])  # c1 is first now but its pull is only "some"
        self.assertEqual((checked["pull"]["c2"], list(checked["clashes"])), ("none", ["c2"]))

    def test_the_order_is_made_whole_and_agrees_with_the_pull(self) -> None:
        checked = validate_choice({"pull": {"c1": "strong", "c3": "some"}, "order": ["c3", "c9", "c1", "c3"], "best": "c3"}, self.index)
        self.assertEqual(checked["order"], ["c1", "c3", "c2"])  # strong first, the missing one last
        self.assertEqual((checked["best"], checked["complete"]), ("c1", False))
        self.assertEqual(checked["pull"]["c2"], "none")

    def test_nobody_is_an_answer_and_a_weak_first_pick_is_not_best(self) -> None:
        self.assertIsNone(validate_choice({"pull": {"c1": "some"}, "order": ["c1", "c2", "c3"], "best": "c1"}, self.index)["best"])
        self.assertIsNone(validate_choice({"pull": {"c1": "strong"}, "order": ["c1", "c2", "c3"], "best": None}, self.index)["best"])
        empty = validate_choice("not json", self.index)
        self.assertEqual((empty["best"], empty["order"], empty["reasons"]), (None, ["c1", "c2", "c3"], []))


def answer(best: str | None, pull: dict[str, str], order: list[str], **extra):
    return {"pull": pull, "order": order, "best": best, **extra}


class ChooseTest(unittest.IsolatedAsyncioTestCase):
    async def test_the_second_look_confirms_and_its_reasons_are_kept(self) -> None:
        async def judge(text: str, **_: object) -> dict:
            pack = json.loads(text)
            keys = {c["name"]: c["key"] for c in pack["candidates"]}
            k = keys["Kabir"]
            reason = {"mine": "p:2", "theirs": f"{k}:2", "text": "Both play FIFA at night." if len(keys) > 1 else "Aarav and Kabir both play FIFA at night, alone look."}
            return answer(k, {key: "strong" if key == k else "none" for key in keys.values()}, [k] + [key for key in keys.values() if key != k], reasons=[reason])

        with patch("agent.providers.choose_match", AsyncMock(side_effect=judge)) as call:
            choice = await choose_among(ME, [MEERA, KABIR, VIKRAM], rng=random.Random(1))
        self.assertEqual(call.await_count, 2)
        self.assertEqual((choice.best, choice.first_pick, choice.order[0]), ("u-kabir", "u-kabir", "u-kabir"))
        self.assertEqual(choice.reasons, [{"text": "Aarav and Kabir both play FIFA at night, alone look.", "mine": "note", "theirs": "note"}])
        self.assertTrue(choice.askable)
        self.assertEqual(choice.rank_of("u-kabir"), 1)

    async def test_the_second_look_can_take_the_pick_back(self) -> None:
        async def judge(text: str, **_: object) -> dict:
            pack = json.loads(text)
            keys = [c["key"] for c in pack["candidates"]]
            if len(keys) == 1:  # alone, the least bad of a weak set is not strong
                return answer(None, {keys[0]: "some"}, keys, why_not={keys[0]: "Only the hours fit."})
            return answer(keys[0], {key: "strong" if key == keys[0] else "none" for key in keys}, keys, reasons=[{"mine": "p:2", "theirs": f"{keys[0]}:1", "text": "x"}])

        with patch("agent.providers.choose_match", AsyncMock(side_effect=judge)):
            choice = await choose_among(ME, [MEERA, VIKRAM], rng=random.Random(1))
        self.assertIsNone(choice.best)
        self.assertIsNotNone(choice.first_pick)
        self.assertEqual((choice.pull[choice.first_pick], choice.reasons, choice.askable), ("some", [], False))
        self.assertEqual(choice.why_not[choice.first_pick], "Only the hours fit.")
        self.assertEqual(len(choice.order), 2)

    async def test_when_the_first_pick_is_taken_back_the_next_strong_one_gets_its_look(self) -> None:
        async def judge(text: str, **_: object) -> dict:
            pack = json.loads(text)
            keys = {c["name"]: c["key"] for c in pack["candidates"]}
            if len(keys) == 1:
                name, key = next(iter(keys.items()))
                if name == "Kabir":
                    return answer(key, {key: "strong"}, [key], reasons=[{"mine": "p:2", "theirs": f"{key}:2", "text": "Both play FIFA at night."}])
                return answer(None, {key: "none"}, [key], why_not={key: "Only the surface fits."})
            v, k, m = keys["Vikram"], keys["Kabir"], keys["Meera"]
            return answer(v, {v: "strong", k: "strong", m: "none"}, [v, k, m], reasons=[{"mine": "p:2", "theirs": f"{v}:1", "text": "Both play FIFA at night."}])

        with patch("agent.providers.choose_match", AsyncMock(side_effect=judge)) as call:
            choice = await choose_among(ME, [MEERA, KABIR, VIKRAM], rng=random.Random(3))
        self.assertEqual(call.await_count, 3)
        self.assertEqual((choice.best, choice.first_pick), ("u-kabir", "u-vikram"))
        self.assertEqual((choice.order[0], choice.pull["u-vikram"]), ("u-kabir", "none"))
        self.assertEqual([r["text"] for r in choice.reasons], ["Both play FIFA at night."])
        self.assertNotIn("u-kabir", choice.why_not)
        self.assertEqual(choice.why_not["u-vikram"], "Only the surface fits.")

    async def test_one_candidate_or_no_pick_means_one_call_and_no_candidates_means_none(self) -> None:
        nobody = AsyncMock(return_value=answer(None, {"c1": "none", "c2": "none"}, ["c1", "c2"]))
        with patch("agent.providers.choose_match", nobody):
            self.assertIsNone((await choose_among(ME, [MEERA, VIKRAM])).best)
            self.assertEqual(nobody.await_count, 1)
            self.assertEqual((await choose_among(ME, [])).order, ())
            self.assertEqual(nobody.await_count, 1)


class NotesTest(unittest.TestCase):
    def test_lines_come_first_and_a_long_memory_list_is_cut_by_closeness_then_importance(self) -> None:
        def vector(x: float, y: float) -> dict:
            return {"provider": "p", "model": "m", "dimensions": 2, "values": [x, y]}

        def memory(n: int, importance: float = 0.1) -> dict:
            return {"id": f"m{n}", "statement": f"statement {n}", "importance": importance, "purposes": ["matching"] if n % 2 else ["profile"], "updated_at": f"2026-11-{n + 1:02d}"}

        memories = tuple(memory(n, importance=0.9 if n == 5 else 0.1) for n in range(6))
        own = Loaded("u", "A", (Note("line", True, area="humor"),), memories, {f"m{n}": vector(1.0, 0.0) if n in (3, 4) else vector(0.0, 1.0) for n in range(6)}, {})
        other = Loaded("v", "B", (), (), {"x": vector(1.0, 0.0)}, {})
        notes = notes_toward(own, [other], limit=4)
        self.assertEqual(notes[0].area, "humor")
        ids = [note.memory_id for note in notes[1:]]
        self.assertEqual(set(ids[:2]), {"m3", "m4"})  # closest to what the other said
        self.assertEqual(ids[2], "m5")  # then the most important
        self.assertEqual(len(ids), 4)
        self.assertEqual({note.memory_id: note.reason_ok for note in notes[1:]}["m3"], True)
        self.assertEqual({note.memory_id: note.reason_ok for note in notes[1:]}["m4"], False)
        # Everything fits: nothing is cut.
        self.assertEqual(len(notes_toward(own, [other], limit=20)), 7)


if __name__ == "__main__":
    unittest.main()
