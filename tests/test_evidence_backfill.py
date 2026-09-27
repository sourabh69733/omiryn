"""Evidence times are moved to the message send time, only when the quote matches."""

from datetime import UTC, datetime

import storage
from storage.evidence_backfill import backfill_evidence_times

USER_ID = "backfill-user"
CONVERSATION_ID = "backfill-conversation"
SENT = "2026-09-14T14:30:00+00:00"
EXTRACTED = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)


def _memory(quote: str, index: int, observed: datetime) -> dict:
    return storage.create_agent_memory(
        {
            "user_id": USER_ID, "kind": "semantic", "purposes": ["profile"], "key": f"k{index}{quote[:3]}",
            "value": "v", "allowed_uses": ["reply_context"], "status": "active", "sensitivity": "standard",
            "confidence": 0.9, "importance": 0.5,
            "evidence": [{"conversation_id": CONVERSATION_ID, "message_index": index, "exact_quote": quote,
                          "observed_at": observed.isoformat()}],
        }
    )


def setup_function() -> None:
    storage.reset_db()
    storage.save_conversation(
        {
            "id": CONVERSATION_ID,
            "status": "active",
            "messages": [
                {"role": "assistant", "content": "hey", "created_at": SENT},
                {"role": "user", "content": "My dog Bruno is a beagle", "created_at": SENT},
                {"role": "user", "content": "no time on this one"},
            ],
        },
        USER_ID,
    )


def test_dry_run_counts_and_apply_fixes_only_matching_rows() -> None:
    wrong = _memory("dog Bruno is a beagle", 1, EXTRACTED)
    _memory("something else entirely", 1, EXTRACTED)
    _memory("no time on this one", 2, EXTRACTED)

    dry = backfill_evidence_times(apply=False)
    assert (dry["fixed"], dry["quote_mismatch"], dry["no_message_time"]) == (1, 1, 1)
    memory = next(m for m in storage.list_agent_memories(USER_ID) if m["id"] == wrong["id"])
    assert memory["evidence"][0]["observed_at"].startswith("2026-09-16")  # unchanged

    backfill_evidence_times(apply=True)
    memory = next(m for m in storage.list_agent_memories(USER_ID) if m["id"] == wrong["id"])
    assert memory["evidence"][0]["observed_at"].startswith("2026-09-14T14:30")
    assert backfill_evidence_times(apply=False)["fixed"] == 0  # safe to re-run
