"""Notes most of a group shares are marked, cannot back a reason, and are flagged for the judge."""

import json
import unittest
from unittest.mock import AsyncMock, patch

from agent.matching.choose import Loaded, Note, Person, choose_pack, validate_choice
from agent.matching.common import common_note_ids, mark_common

JOKES, WALKS, FILMS, CODE = [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [0.6, 0.0, 0.8]


def group(*people: tuple[str, list[tuple[str, str, list[float]]]]) -> dict:
    return dict(people)


class CommonIdsTest(unittest.TestCase):
    def test_a_note_half_the_others_share_is_common_and_a_rare_one_is_not(self) -> None:
        notes = group(
            ("a", [("n1", "humour", JOKES), ("n2", "loves", WALKS)]),
            ("b", [("n1", "humour", JOKES), ("n2", "loves", WALKS)]),
            ("c", [("n1", "humour", JOKES), ("n2", "loves", FILMS)]),
            ("d", [("n1", "humour", JOKES)]),
            ("e", [("n1", "humour", CODE), ("n2", "loves", JOKES)]),  # the same words under another kind do not count
        )
        common = common_note_ids(notes)
        self.assertEqual(common["a"], {"n1"})  # three of four others joke the same way; one other walks
        self.assertEqual(common["c"], {"n1"})
        self.assertEqual(common["e"], set())  # 0.6 from the jokes: not the same thing
        self.assertEqual(common["d"], {"n1"})

    def test_a_small_group_marks_nothing(self) -> None:
        notes = group(*((ref, [("n1", "humour", JOKES)]) for ref in "abcd"))
        self.assertEqual(common_note_ids(notes), {ref: set() for ref in "abcd"})
        # People with no notes do not make a group bigger.
        self.assertEqual(common_note_ids({**notes, "e": []})["a"], set())


def loaded(ref: str, name: str) -> Loaded:
    return Loaded(ref, name, (Note(f"{name} turns daily trouble into a joke.", True, area="humour", note_id="n1"), Note(f"{name} loves thing {ref}.", True, area="loves", note_id="n2"), Note("A vibe line.", True, area="interests")), (), {}, {})


class MarkTest(unittest.IsolatedAsyncioTestCase):
    async def test_the_whole_group_is_embedded_once_without_names_and_only_match_notes_are_marked(self) -> None:
        people = {ref: loaded(ref, name) for ref, name in zip("abcde", ("Aman", "Bela", "Chitra", "Dev", "Esha"))}
        seen: list[str] = []

        async def embed(*, inputs: list[str], **_: object) -> list[list[float]]:
            seen.extend(inputs)
            # The joke notes all point one way; every other note points its own way.
            return [[1.0] + [0.0] * 16 if "joke" in text else [0.0] + [1.0 if k == i else 0.0 for k in range(16)] for i, text in enumerate(inputs)]

        with patch("agent.memory_engine.memories.embeddings.provider_embeddings", AsyncMock(side_effect=embed)) as call, patch("agent.memory_engine.memories.embeddings.memory_embedding_target", lambda: ("p", "m")):
            marked = await mark_common(people)
        self.assertEqual(call.await_count, 1)
        self.assertEqual(len(seen), 10)  # two match notes each; the vibe line is not compared
        self.assertIn("They turns daily trouble into a joke.", seen)
        self.assertFalse(any("Aman" in text for text in seen))
        self.assertEqual([(note.note_id, note.common) for note in marked["a"].lines], [("n1", True), ("n2", False), (None, False)])

    async def test_a_failed_embedding_call_or_a_small_group_changes_nothing(self) -> None:
        people = {ref: loaded(ref, ref.upper()) for ref in "abcde"}
        with patch("agent.memory_engine.memories.embeddings.provider_embeddings", AsyncMock(side_effect=RuntimeError("down"))), patch("agent.memory_engine.memories.embeddings.memory_embedding_target", lambda: ("p", "m")):
            self.assertIs(await mark_common(people), people)
        few = {ref: people[ref] for ref in "abc"}
        call = AsyncMock()
        with patch("agent.memory_engine.memories.embeddings.provider_embeddings", call):
            self.assertIs(await mark_common(few), few)
        call.assert_not_awaited()


class JudgeSideTest(unittest.TestCase):
    def test_a_common_note_is_flagged_in_the_pack_and_cannot_back_a_reason(self) -> None:
        me = Person("me", "Aman", (Note("Aman turns daily trouble into a joke.", True, area="humour", note_id="n1", common=True), Note("Aman loves old films.", True, area="loves", note_id="n2")))
        other = Person("ot", "Bela", (Note("Bela turns daily trouble into a joke.", True, area="humour", note_id="n1", common=True), Note("Bela loves old films.", True, area="loves", note_id="n2")))
        text, index = choose_pack(me, [other])
        pack = json.loads(text)
        self.assertEqual((pack["person"]["notes"][0]["common"], pack["person"]["notes"][0]["reason_ok"]), (True, False))
        self.assertNotIn("common", pack["person"]["notes"][1])
        checked = validate_choice({
            "pull": {"c1": "strong"}, "order": ["c1"], "best": "c1",
            "reasons": [
                {"mine": "p:1", "theirs": "c1:1", "text": "Both turn daily trouble into a joke."},
                {"mine": "p:2", "theirs": "c1:1", "text": "Old films and a joke about trouble."},
                {"mine": "p:2", "theirs": "c1:2", "text": "Both love old films."},
            ],
        }, index)
        self.assertEqual([r["text"] for r in checked["reasons"]], ["Both love old films."])


if __name__ == "__main__":
    unittest.main()
