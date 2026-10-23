"""An upload (both sides) is read in parallel parts, merged into memories and a digest, and tracked."""

import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agent.cognition.background.idle import run_memory_flush_job
from agent.cognition.background.upload_notes import Gathered, check_part, merged_memories
from agent.cognition.background.upload_read import card_lines, merge_vibe, upload_parts
from agent.cognition.background.uploads import learn_from_whatsapp_upload
from agent.memory_engine.memories.models import MemoryKind, MemoryPurpose, MemorySensitivity
from agent.memory_engine.memories.operations import MemoryAddProposal, MemoryReinforceProposal
from api.main import app, current_user
from security.auth import CurrentUser
from storage import get_user_card, list_agent_memories, reset_db, save_conversation, set_user_timezone
from storage.context_sources import get_context_source_metadata, save_context_source
from storage.upload_digests import list_upload_digests

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


def _gathered(*candidates: tuple[str, MemoryAddProposal]) -> Gathered:
    return Gathered(list(candidates), {}, {}, {}, [], {})


class MergeTest(unittest.TestCase):
    def test_a_fact_learned_by_two_parts_is_one_memory_with_both_proofs(self) -> None:
        gathered = _gathered(("c1", _add("Lives in Pune.", (2,))), ("c2", _add("Lives in Pune, Kothrud area.", (40,), 0.9)), ("c3", _add("Plays badminton.", (5,))))
        merged = merged_memories(gathered, {"same": [["c1", "c2"], ["c3", "c99"]]}, [])

        self.assertEqual(len(merged), 2)
        pune = next(item for item in merged if "Pune" in item.statement)
        self.assertEqual(pune.statement, "Lives in Pune, Kothrud area.")
        self.assertEqual(pune.evidence_message_indexes, (2, 40))
        self.assertEqual(pune.confidence, 0.9)

    def test_a_fact_already_remembered_reinforces_that_memory(self) -> None:
        gathered = _gathered(("c1", _add("Lives in Pune.", (2,))))
        [operation] = merged_memories(gathered, {"known": [{"candidate": "c1", "memory": "m1"}, {"candidate": "c1", "memory": "unknown"}]}, [{"id": "m1"}])
        self.assertIsInstance(operation, MemoryReinforceProposal)
        self.assertEqual((operation.target_memory_id, operation.evidence_message_indexes), ("m1", (2,)))

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


class BusyProviderTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_busy_model_is_retried_with_waits_then_the_background_model(self) -> None:
        from zoneinfo import ZoneInfo

        from agent.cognition.background import upload_read

        part = upload_parts("c", "u", [{"role": "user", "content": "I live in Pune and love trekking"}])[0]
        answer = {"threads": [{"title": "Trekking", "summary": "Loves treks.", "lines": [0]}]}
        reader = AsyncMock(side_effect=[RuntimeError("429 busy"), RuntimeError("429 busy"), answer])
        with patch.dict(os.environ, {"MEMORY_UPLOAD_MODEL": "fast-model", "MEMORY_BACKGROUND_V2_MODEL": "big-model"}), patch.object(upload_read, "analyze_upload_part", reader), patch.object(upload_read.asyncio, "sleep", AsyncMock()) as sleep:
            notes = await upload_read._read_part(part, None, ZoneInfo("UTC"))

        self.assertEqual(notes.threads[0]["title"], "Trekking")
        self.assertEqual([call.kwargs["model"] for call in reader.await_args_list], ["fast-model", "fast-model", "big-model"])
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [5.0, 15.0])

    async def test_a_part_that_comes_back_empty_is_read_by_the_other_model(self) -> None:
        from zoneinfo import ZoneInfo

        from agent.cognition.background import upload_read

        part = upload_parts("c", "u", [{"role": "user", "content": "I live in Pune and love trekking"}])[0]
        reader = AsyncMock(side_effect=[{}, {"threads": [{"title": "Trekking", "summary": "x", "lines": [0]}]}])
        with patch.dict(os.environ, {"MEMORY_UPLOAD_MODEL": "fast-model", "MEMORY_BACKGROUND_V2_MODEL": "big-model"}), patch.object(upload_read, "analyze_upload_part", reader), patch.object(upload_read.asyncio, "sleep", AsyncMock()) as sleep:
            notes = await upload_read._read_part(part, None, ZoneInfo("UTC"))

        self.assertFalse(notes.empty)
        self.assertEqual([call.kwargs["model"] for call in reader.await_args_list], ["fast-model", "big-model"])
        sleep.assert_not_awaited()

    def test_notes_citing_lines_outside_the_part_are_dropped(self) -> None:
        part = upload_parts("c", "u", [{"role": "user", "content": "I live in Pune and love trekking"}])[0]
        notes = check_part({"threads": [{"title": "Trek", "lines": [0, 99]}, {"title": "Ghost", "lines": [42]}], "about_user": [{"operation": "add", "memory_kind": "procedural", "key": "k", "value": "v", "statement": "s", "evidence_message_indexes": [0]}]}, part)
        self.assertEqual([(t["title"], t["lines"]) for t in notes.threads], [("Trek", [0])])
        self.assertEqual(notes.memories, ())


class PartsTest(unittest.TestCase):
    def test_parts_cover_every_user_line_once(self) -> None:
        messages = [{"role": "user", "content": f"line number {index} about my day"} for index in range(70)]
        parts = upload_parts("c", "u", messages)
        self.assertEqual(len(parts), 3)
        self.assertEqual(sum(part.meaningful_user_message_count for part in parts), 70)
        self.assertEqual([part.new_start_message_index for part in parts], [0, 30, 60])

    def test_a_long_upload_is_read_from_its_newest_lines(self) -> None:
        from agent.cognition.background import upload_read

        messages = [{"role": "user", "content": f"line number {index} about my day"} for index in range(500)]
        with patch.object(upload_read, "READ_USER_LINES", 120):
            parts = upload_parts("c", "u", messages)
        self.assertEqual(parts[0].new_start_message_index, 380)
        self.assertEqual(sum(part.meaningful_user_message_count for part in parts), 120)


EXPORT = """13/10/2026, 9:15 pm - Farheen: how was the review today
13/10/2026, 9:16 pm - Sourabh: 8th cycle again, this task is never ending
13/10/2026, 9:30 pm - Farheen: same here, my lead keeps changing specs
13/10/2026, 9:31 pm - Sourabh: also finance influencers are clowns, never trust them
"""


class ReadUploadTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.env = patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"})
        self.env.start()
        set_user_timezone(USER_ID, "Asia/Kolkata")
        save_conversation({"id": "main", "status": "active", "messages": []}, USER_ID)
        self.source = save_context_source({"user_id": USER_ID, "conversation_id": "main", "source_type": "whatsapp_chat", "title": "Farheen", "content": "x"})

    def tearDown(self) -> None:
        self.env.stop()

    async def test_both_sides_become_memories_and_a_digest(self) -> None:
        with patch("agent.cognition.background.uploads.request_flush_now"):
            hidden = learn_from_whatsapp_upload(USER_ID, self.source["id"], EXPORT, "Sourabh")
        self.assertEqual(get_context_source_metadata(self.source["id"], USER_ID)["reading"]["state"], "queued")

        def part_answer(payload: str, **_: object) -> dict:
            lines = {m["from"]: m["i"] for m in json.loads(payload)["messages"]}
            mine, hers = lines["user"], lines["Farheen"]
            return {
                "threads": [{"title": "Endless review cycles", "summary": "Both are stuck in long reviews.", "user_view": "Frustrated.", "other_view": "Lead changes specs.", "lines": [mine, hers]}],
                "about_user": [{"operation": "add", "memory_kind": "semantic", "purposes": ["profile"], "key": "views.finance_influencers", "value": "distrusts finance influencers", "statement": "Distrusts finance influencers.", "sensitivity": "standard", "confidence": 0.9, "importance": 0.5, "evidence_message_indexes": [mine]}],
                "about_other": [{"fact": "Her lead keeps changing specs.", "lines": [hers]}],
            }

        merge = {
            "threads": [{"title": "Endless review cycles", "summary": "Both are stuck in long reviews.", "from": ["t1"]}],
            "person": [{"text": "Her lead keeps changing specs.", "from": ["o1"]}],
            "summary": "Two colleagues venting about review work.",
            "index_line": "Farheen: review cycles, finance",
            "relationship": {"statement": "Chats with Farheen on WhatsApp, mostly about review work.", "from": ["t1"]},
            "user_card": "Distrusts finance influencers",
        }
        with patch("agent.cognition.background.upload_read.analyze_upload_part", AsyncMock(side_effect=part_answer)) as reader, patch(
            "agent.cognition.background.upload_read.analyze_upload_merge", AsyncMock(return_value=merge)
        ):
            result = await run_memory_flush_job({"conversation_id": hidden, "user_id": USER_ID})

        self.assertEqual(result["status"], "upload_read")
        self.assertEqual(reader.await_count, 1)
        statements = sorted(m["statement"] for m in list_agent_memories(USER_ID))
        self.assertEqual(statements, ["Chats with Farheen on WhatsApp, mostly about review work.", "Distrusts finance influencers."])
        self.assertEqual(get_user_card(USER_ID), "Distrusts finance influencers")
        [stored] = list_upload_digests(USER_ID)
        digest = stored["digest"]
        self.assertEqual((stored["partner_name"], digest["index_line"]), ("Farheen", "Farheen: review cycles, finance"))
        self.assertEqual(digest["threads"][0]["started"], "2026-10-13")
        self.assertEqual(len(digest["threads"][0]["lines"]), 2)
        self.assertEqual(digest["person"][0]["text"], "Her lead keeps changing specs.")
        reading = get_context_source_metadata(self.source["id"], USER_ID)["reading"]
        self.assertEqual((reading["state"], reading["parts_done"], reading["learned"], reading["topics"]), ("done", 1, 2, 1))
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

    def test_deleting_the_upload_deletes_its_digest(self) -> None:
        from storage.upload_digests import save_upload_digest

        save_upload_digest(self.source["id"], USER_ID, "main", "Farheen", {"summary": "x"})
        self.assertEqual(self.client.delete(f"/api/me/context-sources/{self.source['id']}").status_code, 200)
        self.assertEqual(list_upload_digests(USER_ID), [])

    def test_memories_page_gets_each_uploads_summary_and_topics(self) -> None:
        from storage.upload_digests import save_upload_digest

        save_upload_digest(self.source["id"], USER_ID, "main", "Farheen", {"summary": "Work chat.", "threads": [{"title": "Review cycles", "started": "2026-10-15", "lines": [1, 2]}]})
        [source] = [s for s in self.client.get("/api/me/profile").json()["memory_sources"] if s["id"] == self.source["id"]]
        self.assertEqual(source["digest"]["summary"], "Work chat.")
        self.assertEqual(source["digest"]["topics"], [{"title": "Review cycles", "started": "2026-10-15", "ended": None}])

    def test_progress_is_readable_and_owned(self) -> None:
        response = self.client.get(f"/api/me/context-sources/{self.source['id']}/reading")
        self.assertEqual(response.json()["parts_done"], 2)
        self.assertEqual(self.client.get("/api/me/context-sources/someone-else/reading").status_code, 404)


if __name__ == "__main__":
    unittest.main()
