"""An upload is read in parallel parts, merged once, and reports its progress."""

import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agent.cognition.background.idle import run_memory_flush_job
from agent.cognition.background.upload_read import card_lines, merge_operations, merge_vibe, upload_parts
from agent.cognition.background.uploads import learn_from_notes_upload
from agent.memory_engine.memories.models import MemoryKind, MemoryPurpose, MemorySensitivity
from agent.memory_engine.memories.operations import MemoryAddProposal, MemoryReinforceProposal
from api.main import app, current_user
from security.auth import CurrentUser
from storage import get_user_card, list_agent_memories, reset_db, save_conversation
from storage.context_sources import get_context_source_metadata, save_context_source

USER_ID = "upload-read-user"


def _add(statement: str, evidence: tuple[int, ...], confidence: float = 0.8) -> MemoryAddProposal:
    return MemoryAddProposal(
        kind=MemoryKind.SEMANTIC,
        purposes=frozenset({MemoryPurpose.PROFILE}),
        key="home.city",
        value=statement,
        sensitivity=MemorySensitivity.STANDARD,
        confidence=confidence,
        importance=0.6,
        evidence_message_indexes=evidence,
        statement=statement,
    )


class MergeTest(unittest.TestCase):
    def test_a_fact_learned_by_two_parts_is_one_memory_with_both_proofs(self) -> None:
        candidates = [("c1", _add("Lives in Pune.", (2,))), ("c2", _add("Lives in Pune, Kothrud area.", (40,), 0.9)), ("c3", _add("Plays badminton.", (5,)))]
        merged = merge_operations(candidates, {}, [["c1", "c2"], ["c3", "c99"]])

        self.assertEqual(len(merged), 2)
        pune = next(item for item in merged if "Pune" in item.statement)
        self.assertEqual(pune.statement, "Lives in Pune, Kothrud area.")
        self.assertEqual(pune.evidence_message_indexes, (2, 40))
        self.assertEqual(pune.confidence, 0.9)

    def test_changes_to_existing_memories_pass_through(self) -> None:
        reinforce = MemoryReinforceProposal(target_memory_id="m1", confidence=0.9, importance=0.5, evidence_message_indexes=(3,))
        self.assertEqual(merge_operations([], {"m1": reinforce}, "not a list"), (reinforce,))

    def test_vibe_line_keeps_the_proof_of_the_lines_it_joined(self) -> None:
        proof = lambda index: {"conversation_id": "u", "message_index": index}  # noqa: E731
        candidates = {"humor": [{"id": "v1", "text": "Dry jokes.", "evidence": [proof(1)]}, {"id": "v2", "text": "Teases friends.", "evidence": [proof(9)]}]}
        updates = merge_vibe({"humor": {"line": "Dry jokes and teasing.", "from": ["v1", "v2"]}}, candidates)
        self.assertEqual(updates["humor"]["text"], "Dry jokes and teasing.")
        self.assertEqual([item["message_index"] for item in updates["humor"]["evidence"]], [1, 9])

    def test_a_vibe_line_can_rest_on_the_proof_of_memories(self) -> None:
        proof = {"c2": [{"conversation_id": "u", "message_index": 7}]}
        updates = merge_vibe({"values": {"line": "Cannot stand liars.", "from": ["c2"]}, "humor": {"line": "Funny.", "from": []}}, {}, proof)
        self.assertEqual(updates, {"values": {"text": "Cannot stand liars.", "evidence": proof["c2"]}})

    def test_a_card_written_as_a_list_or_paragraph_becomes_lines(self) -> None:
        self.assertEqual(card_lines(["Lives in Pune.", " ", "Plays badminton."]), "Lives in Pune.\nPlays badminton.")
        self.assertEqual(card_lines("Lives in Pune. Plays badminton."), "Lives in Pune.\nPlays badminton.")
        self.assertEqual(card_lines("Lives in Pune\nPlays badminton"), "Lives in Pune\nPlays badminton")

    def test_an_area_the_wrap_up_skipped_keeps_its_best_line(self) -> None:
        candidates = {"humor": [{"id": "v1", "text": "Dry jokes.", "evidence": [{"conversation_id": "u", "message_index": 1}]}]}
        self.assertEqual(merge_vibe({}, candidates)["humor"]["text"], "Dry jokes.")


class PartsTest(unittest.TestCase):
    def test_parts_cover_every_user_line_once(self) -> None:
        messages = [{"role": "user", "content": f"line number {index} about my day"} for index in range(70)]
        parts = upload_parts("c", "u", messages)
        self.assertEqual(len(parts), 3)
        self.assertEqual(sum(part.meaningful_user_message_count for part in parts), 70)
        self.assertEqual([part.new_start_message_index for part in parts], [0, 30, 60])


class ReadUploadTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.env = patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"})
        self.env.start()
        save_conversation({"id": "main", "status": "active", "messages": []}, USER_ID)
        self.source = save_context_source({"user_id": USER_ID, "conversation_id": "main", "source_type": "manual_notes", "title": "Notes", "content": "x"})

    def tearDown(self) -> None:
        self.env.stop()

    async def test_fresh_upload_is_read_in_parts_merged_and_tracked(self) -> None:
        with patch("agent.cognition.background.uploads.request_flush_now"):
            hidden = learn_from_notes_upload(USER_ID, self.source["id"], "I live in Pune.\n\nI play badminton every weekend.")
        self.assertEqual(get_context_source_metadata(self.source["id"], USER_ID)["reading"]["state"], "queued")

        def part_answer(payload: str, **_: object) -> dict:
            index = next(m["message_index"] for m in json.loads(payload)["messages"] if m["role"] == "user" and m["evidence_eligible"])
            return {
                "decision": "propose",
                "operations": [{"operation": "add", "memory_kind": "semantic", "purposes": ["profile"], "key": "home.city", "value": "Pune", "statement": "Lives in Pune.", "sensitivity": "standard", "confidence": 0.9, "importance": 0.6, "evidence_message_indexes": [index]}],
                "thread_operation": {"operation": "none"},
                "handoff": {"summary": "", "active_people": [], "active_topics": [], "unresolved_references": []},
                "user_card": None,
                "vibe": {},
            }

        wrap = {"same": [], "user_card": "Lives in Pune", "vibe": {}}
        with patch("agent.cognition.background.upload_read.analyze_background_cognition", AsyncMock(side_effect=part_answer)) as reader, patch(
            "agent.cognition.background.upload_read.analyze_upload_wrap_up", AsyncMock(return_value=wrap)
        ):
            result = await run_memory_flush_job({"conversation_id": hidden, "user_id": USER_ID})

        self.assertEqual(result["status"], "upload_read")
        self.assertEqual(reader.await_count, 1)
        self.assertEqual([m["statement"] for m in list_agent_memories(USER_ID)], ["Lives in Pune."])
        self.assertEqual(get_user_card(USER_ID), "Lives in Pune")
        reading = get_context_source_metadata(self.source["id"], USER_ID)["reading"]
        self.assertEqual((reading["state"], reading["parts_done"], reading["learned"]), ("done", 1, 1))
        # Read once: the normal flush finds nothing left.
        again = await run_memory_flush_job({"conversation_id": hidden, "user_id": USER_ID})
        self.assertEqual(again["status"], "no_pending_messages")


class ReadingEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id=USER_ID, email="u@example.com", display_name="U")

        app.dependency_overrides[current_user] = signed_in_user
        self.env = patch.dict(os.environ, {"AUTH_REQUIRED": "false"})
        self.env.start()
        save_conversation({"id": "main", "status": "active", "messages": []}, USER_ID)
        self.source = save_context_source({"user_id": USER_ID, "conversation_id": "main", "source_type": "manual_notes", "title": "Notes", "content": "x", "metadata": {"reading": {"state": "reading", "parts": 5, "parts_done": 2}}})
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.env.stop()

    def test_progress_is_readable_and_owned(self) -> None:
        response = self.client.get(f"/api/me/context-sources/{self.source['id']}/reading")
        self.assertEqual(response.json()["parts_done"], 2)
        self.assertEqual(self.client.get("/api/me/context-sources/someone-else/reading").status_code, 404)


if __name__ == "__main__":
    unittest.main()
