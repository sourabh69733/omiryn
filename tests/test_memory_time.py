import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from agent.context_engine.assembly.sources import _memory_time_note
from agent.memory_engine.memories.application import _trusted_evidence
from agent.memory_engine.memories.prompt import V3_MEMORY_OUTPUT_SHAPE
from agent.memory_engine.processing.context import build_memory_batch
from agent.memory_engine.processing.prompt import memory_batch_prompt

SENT = datetime(2026, 9, 22, 19, 30, tzinfo=UTC)  # Wed 23 Sep, 1:00 am in Asia/Kolkata
EXTRACTED = datetime(2026, 9, 23, 6, 0, tzinfo=UTC)


def _batch(created_at: str | None = SENT.isoformat()):
    user_message = {"role": "user", "content": "My interview was yesterday and it went well"}
    if created_at:
        user_message["created_at"] = created_at
    return build_memory_batch(
        conversation_id="conversation-1",
        user_id="user-1",
        messages=[{"role": "assistant", "content": "hey"}, user_message],
    )


def test_batch_prompt_gives_local_send_time_for_relative_dates() -> None:
    payload = json.loads(memory_batch_prompt(_batch(), [], "Asia/Kolkata"))
    user_message = payload["messages"][-1]

    assert payload["user_timezone"] == "Asia/Kolkata"
    assert user_message["sent_at"] == "2026-09-23T01:00+05:30"
    assert user_message["sent_weekday"] == "Wednesday"
    assert "sent_at" not in payload["messages"][0]


def test_batch_prompt_omits_send_time_when_unknown() -> None:
    payload = json.loads(memory_batch_prompt(_batch(created_at=None), [], "Asia/Kolkata"))
    assert "sent_at" not in payload["messages"][-1]


def test_prompt_asks_model_to_resolve_relative_dates_from_send_time() -> None:
    assert "yesterday" in V3_MEMORY_OUTPUT_SHAPE
    assert "sent_at" in V3_MEMORY_OUTPUT_SHAPE


def test_evidence_records_when_the_user_said_it() -> None:
    evidence = _trusted_evidence(_batch(), (1,), EXTRACTED)
    assert evidence[0]["observed_at"] == SENT.isoformat()


def test_evidence_falls_back_to_extraction_time_without_send_time() -> None:
    evidence = _trusted_evidence(_batch(created_at=None), (1,), EXTRACTED)
    assert evidence[0]["observed_at"] == EXTRACTED.isoformat()


def test_memory_note_shows_first_and_latest_mention_in_user_timezone() -> None:
    memory = {
        "occurred_at": "2026-09-21T12:00:00+05:30",
        "evidence": [
            {"observed_at": "2026-09-22T19:30:00+00:00"},
            {"observed_at": "2026-09-22T20:00:00+00:00"},
            {"observed_at": "2026-09-01T08:00:00+00:00"},
        ],
    }
    note = _memory_time_note(memory, ZoneInfo("Asia/Kolkata"))

    assert note == " (told you 1 Sep 2026, again 23 Sep 2026; happened 21 Sep 2026)"


def test_memory_note_is_empty_without_dates() -> None:
    assert _memory_time_note({"evidence": []}, ZoneInfo("UTC")) == ""
