import unittest
from datetime import datetime, timedelta, timezone

from agent.memory_engine.memories.vibe import proof_after_rejection, rejected_texts
from storage import get_vibe_card, reset_db, update_vibe_card


def proof(index: int, sent_at: datetime | None) -> dict:
    item = {"conversation_id": "c1", "message_index": index}
    if sent_at:
        item["sent_at"] = sent_at.isoformat()
    return item


OLD = datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)


def later() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=1)


class ProofAfterRejectionTest(unittest.TestCase):
    rejected = {"humor": {"text": "Dark jokes.", "evidence": [proof(1, OLD)], "at": "2026-10-01T12:00:00+00:00"}}

    def test_old_proof_cannot_bring_a_rejected_line_back(self) -> None:
        updates = {"humor": {"text": "Dark jokes.", "evidence": [proof(1, OLD), proof(2, OLD)]}}

        self.assertEqual(proof_after_rejection(updates, self.rejected), {})

    def test_proof_after_the_rejection_is_kept(self) -> None:
        new = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
        updates = {"humor": {"text": "Puns.", "evidence": [proof(1, OLD), proof(7, new)]}}

        self.assertEqual(proof_after_rejection(updates, self.rejected), {"humor": {"text": "Puns.", "evidence": [proof(7, new)]}})

    def test_proof_without_a_time_does_not_count(self) -> None:
        updates = {"humor": {"text": "Puns.", "evidence": [proof(7, None)]}}

        self.assertEqual(proof_after_rejection(updates, self.rejected), {})

    def test_other_areas_pass_through(self) -> None:
        updates = {"values": {"text": "Honesty.", "evidence": [proof(3, OLD)]}}

        self.assertEqual(proof_after_rejection(updates, self.rejected), updates)

    def test_rejected_texts_for_prompts(self) -> None:
        self.assertEqual(rejected_texts(self.rejected), {"humor": "Dark jokes."})


class RejectStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        update_vibe_card("reject-user", {"humor": {"text": "Dark jokes.", "evidence": [proof(1, OLD)]}})

    def test_reject_removes_the_line_and_remembers_it(self) -> None:
        saved = update_vibe_card("reject-user", {}, reject=("humor",))

        self.assertNotIn("humor", saved["areas"])
        card = get_vibe_card("reject-user")
        self.assertNotIn("humor", card["areas"])
        self.assertEqual(card["rejected"]["humor"]["text"], "Dark jokes.")
        self.assertEqual(card["rejected"]["humor"]["evidence"], [proof(1, OLD)])

    def test_same_old_proof_is_refused_after_reject(self) -> None:
        update_vibe_card("reject-user", {}, reject=("humor",))

        saved = update_vibe_card("reject-user", {"humor": {"text": "Dark jokes.", "evidence": [proof(1, OLD)]}})

        self.assertEqual(saved["applied"], ())
        self.assertNotIn("humor", get_vibe_card("reject-user")["areas"])
        self.assertIn("humor", get_vibe_card("reject-user")["rejected"])

    def test_new_proof_writes_the_area_and_clears_the_mark(self) -> None:
        update_vibe_card("reject-user", {}, reject=("humor",))
        new = later()

        saved = update_vibe_card("reject-user", {"humor": {"text": "Puns.", "evidence": [proof(9, new)]}})

        self.assertEqual(saved["applied"], ("humor",))
        card = get_vibe_card("reject-user")
        self.assertEqual(card["areas"]["humor"]["text"], "Puns.")
        self.assertEqual(card["areas"]["humor"]["evidence"], [proof(9, new)])
        self.assertEqual(card["rejected"], {})

    def test_other_areas_still_update(self) -> None:
        update_vibe_card("reject-user", {}, reject=("humor",))

        saved = update_vibe_card("reject-user", {"values": {"text": "Honesty.", "evidence": [proof(2, OLD)]}})

        self.assertEqual(saved["applied"], ("values",))
        self.assertEqual(get_vibe_card("reject-user")["areas"]["values"]["text"], "Honesty.")


if __name__ == "__main__":
    unittest.main()
