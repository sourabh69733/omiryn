"""Old debug records lose chat text but keep the counts, IDs and labels code still reads."""

import unittest
from datetime import timedelta

from sqlalchemy import update

from agent.shared.clock import utc_now
from storage import reset_db
from storage.database import ENGINE
from storage.debug_scrub import scrub_debug_records, scrub_text
from storage.schema import agent_context_snapshots, agent_trace_steps, data_point_extraction_debug

USER_ID = "scrub-user"


def _insert(table, **values) -> None:
    with ENGINE.begin() as connection:
        connection.execute(table.insert().values(user_id=USER_ID, **values))


def _row(table, row_id):
    with ENGINE.begin() as connection:
        return connection.execute(table.select().where(table.c.id == row_id)).mappings().one()


class ScrubTextTest(unittest.TestCase):
    def test_free_text_goes_labels_and_numbers_stay(self) -> None:
        raw = {
            "status": "live_applied",
            "model": "Qwen/Qwen3-235B-A22B-Instruct-2507",
            "count": 3,
            "valid": True,
            "reason": 'it nearly repeats your earlier reply "I live in Pune"',
            "operations": [{"statement": "Lives in Pune.", "message_index": 2}],
        }

        self.assertEqual(
            scrub_text(raw),
            {"status": "live_applied", "model": "Qwen/Qwen3-235B-A22B-Instruct-2507", "count": 3, "valid": True, "operations": [{"message_index": 2}]},
        )


class ScrubRecordsTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        _insert(
            agent_context_snapshots,
            id="snap",
            conversation_id="c",
            message_index=1,
            summary_json={"model": "m", "intent_labels": ["x"], "source_count": 2},
            context_json={
                "prompt": {"system_prompt": "You are Omi... the user said I miss my ex"},
                "sources": [{"source_type": "might_fit", "content": "Loves films", "metadata": {"memory_ids": ["m1"]}}],
            },
        )
        _insert(agent_trace_steps, id="step", trace_id="t", conversation_id="c", step_index=0, step_name="model_call", status="failed",
                metadata_json={"error_type": "ValueError", "error": "could not parse: I miss my ex"})
        _insert(data_point_extraction_debug, id="old", source_kind="agent_conversation", source_id="c", decision="live_applied",
                candidate_json={"handoff": {"summary": "The user misses their ex."}, "batch": 4},
                review_json={"valid": True}, metadata_json={"extractor": "background_cognition_v3"})
        _insert(data_point_extraction_debug, id="new", source_kind="agent_conversation", source_id="c", decision="live_applied",
                candidate_json={"handoff": {"summary": "Recent batch."}}, review_json={}, metadata_json={})
        with ENGINE.begin() as connection:
            connection.execute(
                update(data_point_extraction_debug)
                .where(data_point_extraction_debug.c.id == "old")
                .values(created_at=utc_now() - timedelta(days=30))
            )

    def test_dry_run_counts_and_changes_nothing(self) -> None:
        counts = scrub_debug_records(apply=False)

        self.assertEqual(counts, {"context_snapshots": 1, "trace_steps": 1, "background_debug": 1})
        self.assertIn("prompt", _row(agent_context_snapshots, "snap")["context_json"])

    def test_apply_removes_text_and_keeps_what_code_reads(self) -> None:
        scrub_debug_records(apply=True)

        snapshot = _row(agent_context_snapshots, "snap")
        self.assertEqual(snapshot["summary_json"], {"model": "m", "source_count": 2})
        self.assertEqual(snapshot["context_json"], {"sources": [{"source_type": "might_fit", "metadata": {"memory_ids": ["m1"]}}]})
        self.assertEqual(_row(agent_trace_steps, "step")["metadata_json"], {"error_type": "ValueError"})
        old = _row(data_point_extraction_debug, "old")
        self.assertEqual((old["candidate_json"], old["metadata_json"]), ({"handoff": {}, "batch": 4}, {"extractor": "background_cognition_v3"}))
        self.assertEqual(_row(data_point_extraction_debug, "new")["candidate_json"], {"handoff": {"summary": "Recent batch."}})
        self.assertEqual(scrub_debug_records(apply=False), {"context_snapshots": 0, "trace_steps": 0, "background_debug": 0})


if __name__ == "__main__":
    unittest.main()
