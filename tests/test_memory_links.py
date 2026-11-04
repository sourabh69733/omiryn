"""Memory links: memories about the same name lead to each other."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from agent.context_engine.sources.memories import memory_time_note
from agent.memory_engine.memories.fill_names import fill_memory_names
from agent.memory_engine.memories.links import linked_memories, names_in_text, normalize_about
from agent.memory_engine.memories.retrieval import retrieve_agent_memories_for_reply
from agent.memory_engine.memories.validation import _ADD_FIELDS, _validate_add
from agent.shared.timeline import user_zone
from storage import create_agent_memory, delete_agent_memory, list_agent_memories, reset_db, save_conversation
from storage.memories import set_agent_memory_about

USER_ID = "links-user"


def _memory(statement: str, about: list[str] | None = None, **fields) -> dict:
    source = f"src-{statement[:12]}"
    save_conversation({"id": source, "status": "completed", "messages": [{"role": "user", "content": statement}]}, USER_ID)
    return create_agent_memory(
        {
            "user_id": USER_ID, "kind": "episodic", "purposes": ["personalization"], "key": statement[:24],
            "value": statement, "statement": statement, "confidence": 0.9, "importance": 0.5, "about": about or [],
            "evidence": [{"conversation_id": source, "message_index": 0, "exact_quote": statement, "observed_at": "2026-10-01T10:00:00+00:00"}],
            **fields,
        }
    )


def _item(id_: str, about: list[str], importance: float = 0.5) -> dict:
    return {"id": id_, "about": about, "importance": importance, "confidence": 0.5}


class NamesTest(unittest.TestCase):
    def test_keeps_short_names_once(self) -> None:
        self.assertEqual(normalize_about([" Riya ", "riya", "Pune", 7, "", "x" * 61]), ("Riya", "Pune"))
        self.assertEqual(normalize_about("Riya"), ())
        self.assertEqual(normalize_about(None), ())
        self.assertEqual(len(normalize_about([f"n{i}" for i in range(9)])), 5)

    def test_names_match_whole_words_only(self) -> None:
        names = {"riya", "design studio", "pune"}
        self.assertEqual(names_in_text("Riya ka kya haal?", names), {"riya"})
        self.assertEqual(names_in_text("riya's birthday, design studio", names), {"riya", "design studio"})
        self.assertEqual(names_in_text("kariyar ki baat", names), set())

    def test_validation_keeps_the_memory_when_about_is_bad(self) -> None:
        raw = {
            "operation": "add", "memory_kind": "episodic", "purposes": ["personalization"], "key": "fight",
            "value": "Fought with sister", "statement": "Fought with their sister.", "sensitivity": "standard",
            "confidence": 0.9, "importance": 0.5, "evidence_message_indexes": [0],
        }
        for about, expected in ((["Riya"], ("Riya",)), ("Riya", ()), (None, ())):
            proposal, errors = _validate_add({**raw, "about": about}, eligible_indexes={0}, expected_operation="add", allowed_fields=_ADD_FIELDS)
            self.assertEqual(errors, [])
            self.assertEqual(proposal.about, expected)


class WalkTest(unittest.TestCase):
    def test_only_a_name_the_message_says_leads_anywhere(self) -> None:
        top = _item("top", ["Pune"])
        said = _item("said", ["Riya"], 0.1)
        same_as_top = _item("same", ["Pune"], 0.9)
        self.assertEqual([m["id"] for m in linked_memories([top], [top, said, same_as_top], "riya kaisi hai")], ["said"])

    def test_nothing_shared_nothing_added_and_the_limit_holds(self) -> None:
        top = _item("top", [])
        self.assertEqual(linked_memories([top], [top, _item("x", ["X"])], "hi"), [])
        many = [_item(str(i), ["Riya"]) for i in range(9)]
        self.assertEqual(len(linked_memories([], many, "riya")), 3)


class StoredLinksTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()

    def test_saved_read_back_and_gone_with_the_memory(self) -> None:
        memory = _memory("Sister's birthday is on 8 November.", ["Riya"])
        self.assertEqual(memory["about"], ["Riya"])
        self.assertTrue(set_agent_memory_about(memory["id"], USER_ID, ["Riya", "Delhi"]))
        self.assertEqual(list_agent_memories(USER_ID)[0]["about"], ["Riya", "Delhi"])
        self.assertTrue(delete_agent_memory(memory["id"], USER_ID))
        self.assertEqual(list_agent_memories(USER_ID), [])

    def _recall(self, text: str) -> list[str]:
        return [m["statement"] for m in retrieve_agent_memories_for_reply(USER_ID, text)]

    def test_a_named_person_brings_memories_that_never_say_the_name(self) -> None:
        _memory("Had a big fight with their sister.", ["Riya"])
        _memory("Loves old films.", kind="semantic")
        self.assertEqual(self._recall("riya kaisi hai?"), ["Had a big fight with their sister."])
        with patch.dict("os.environ", {"AGENT_MEMORY_LINKS": "false"}):
            self.assertEqual(self._recall("riya kaisi hai?"), [])

    def test_private_memories_stay_out_of_the_walk(self) -> None:
        _memory("Has a medical condition.", ["Riya"], sensitivity="highly_sensitive")
        self.assertEqual(self._recall("riya kaisi hai?"), [])

    def test_a_reply_is_told_the_name_a_memory_does_not_say(self) -> None:
        zone = user_zone("Asia/Kolkata")
        note = memory_time_note({"statement": "Had a fight with their sister.", "about": ["Riya"]}, zone)
        self.assertIn("about Riya", note)
        self.assertEqual(memory_time_note({"statement": "Riya lives in Pune.", "about": ["Riya"]}, zone), "")


class FillNamesTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        self.sister = _memory("Had a big fight with their sister.")
        self.named = _memory("Has a dog.", ["Bruno"])
        self.style = _memory("Wants short replies.", kind="procedural")

    def test_dry_run_counts_and_calls_no_model(self) -> None:
        with patch("agent.providers.write_memory_names", new=AsyncMock()) as model:
            counts = asyncio.run(fill_memory_names(USER_ID))
        model.assert_not_awaited()
        self.assertEqual(counts, {"memories": 3, "without_names": 1, "named": 0})
        self.assertEqual(self._about(self.sister), [])

    def test_apply_saves_only_memories_it_was_asked_about(self) -> None:
        answer = {"names": {self.sister["id"]: ["Riya"], self.named["id"]: ["Wrong"], "made-up": ["X"]}}
        with patch("agent.providers.write_memory_names", new=AsyncMock(return_value=answer)) as model:
            counts = asyncio.run(fill_memory_names(USER_ID, apply=True))
        self.assertEqual(counts["named"], 1)
        self.assertEqual(self._about(self.sister), ["Riya"])
        self.assertEqual(self._about(self.named), ["Bruno"])
        sent = model.await_args.args[0]
        self.assertIn("Bruno", sent)
        self.assertNotIn("Wants short replies", sent)

    def test_a_bad_answer_changes_nothing(self) -> None:
        with patch("agent.providers.write_memory_names", new=AsyncMock(return_value={"names": "nope"})):
            self.assertEqual(asyncio.run(fill_memory_names(USER_ID, apply=True))["named"], 0)

    def _about(self, memory: dict) -> list[str]:
        return next(item["about"] for item in list_agent_memories(USER_ID) if item["id"] == memory["id"])


if __name__ == "__main__":
    unittest.main()
