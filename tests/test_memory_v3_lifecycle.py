"""Verifies atomic, evidence-grounded v3 memory lifecycle changes."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import storage
from agent.memory_engine.memories.application import apply_validated_memory_analysis_v3
from agent.memory_engine.memories.validation import validate_memory_analysis_v3
from agent.memory_engine.processing import MemoryProcessingState, build_memory_batch


USER_ID = "memory-v3-lifecycle-user"
CONVERSATION_ID = "memory-v3-lifecycle-conversation"


@pytest.fixture(autouse=True)
def _database() -> None:
    storage.reset_db()


def _memory(value: str = "Bengaluru") -> dict[str, object]:
    storage.save_conversation(
        {
            "id": CONVERSATION_ID,
            "status": "active",
            "messages": [{"role": "user", "content": f"I live in {value}."}],
        },
        USER_ID,
    )
    return storage.create_agent_memory(
        {
            "user_id": USER_ID,
            "kind": "semantic",
            "purposes": ["profile"],
            "key": "home.location",
            "value": value,
            "confidence": 0.8,
            "importance": 0.7,
            "evidence": [
                {
                    "conversation_id": CONVERSATION_ID,
                    "message_index": 0,
                    "exact_quote": f"I live in {value}.",
                    "observed_at": "2026-09-01T10:00:00Z",
                }
            ],
        }
    )


def _batch(message: str):
    batch = build_memory_batch(
        conversation_id=CONVERSATION_ID,
        user_id=USER_ID,
        messages=[
            {"role": "user", "content": "I live in Bengaluru."},
            {"role": "assistant", "content": "Got it."},
            {"role": "user", "content": message},
        ],
        state=MemoryProcessingState(
            conversation_id=CONVERSATION_ID,
            user_id=USER_ID,
            processed_through_message_index=1,
        ),
    )
    assert batch is not None
    return batch


def _analysis(operation: dict[str, object], *, target_id: str):
    batch = _batch(str(operation.pop("message")))
    raw = {
        "decision": "propose",
        "operations": [operation],
        "handoff": {
            "summary": "",
            "active_people": [],
            "active_topics": [],
            "unresolved_references": [],
        },
    }
    result = validate_memory_analysis_v3(
        raw,
        batch=batch,
        existing_memory_ids={target_id},
    )
    assert result.valid, result.errors
    return batch, result


def test_reinforce_appends_evidence_without_changing_meaning() -> None:
    existing = _memory()
    batch, analysis = _analysis(
        {
            "operation": "reinforce",
            "target_memory_id": existing["id"],
            "confidence": 0.95,
            "importance": 0.8,
            "evidence_message_indexes": [2],
            "message": "Yes, Bengaluru is still home.",
        },
        target_id=str(existing["id"]),
    )

    applied = apply_validated_memory_analysis_v3(batch, analysis, extractor_model="test-model")
    updated = storage.get_agent_memory(str(existing["id"]), USER_ID)

    assert applied.applied_count == 1
    assert updated is not None
    assert updated["value"] == "Bengaluru"
    assert updated["confidence"] == 0.95
    assert updated["last_reinforced_at"] is not None
    assert len(updated["evidence"]) == 2


def test_supersede_preserves_old_memory_and_creates_corrected_memory() -> None:
    existing = _memory()
    batch, analysis = _analysis(
        {
            "operation": "supersede",
            "target_memory_id": existing["id"],
            "memory_kind": "semantic",
            "purposes": ["profile"],
            "key": "home.location",
            "value": "Pune",
            "sensitivity": "standard",
            "confidence": 0.98,
            "importance": 0.8,
            "occurred_at": None,
            "valid_from": datetime.now(UTC).isoformat(),
            "valid_until": None,
            "evidence_message_indexes": [2],
            "message": "I moved to Pune; I no longer live in Bengaluru.",
        },
        target_id=str(existing["id"]),
    )

    applied = apply_validated_memory_analysis_v3(batch, analysis, extractor_model="test-model")
    memories = storage.list_agent_memories(USER_ID)
    old = next(item for item in memories if item["id"] == existing["id"])
    replacement = next(item for item in memories if item["id"] != existing["id"])

    assert applied.applied_count == 1
    assert old["status"] == "superseded"
    assert replacement["status"] == "active"
    assert replacement["value"] == "Pune"
    assert replacement["supersedes_memory_id"] == existing["id"]


def test_retract_keeps_auditable_memory_but_removes_it_from_active_state() -> None:
    existing = _memory()
    batch, analysis = _analysis(
        {
            "operation": "retract",
            "target_memory_id": existing["id"],
            "evidence_message_indexes": [2],
            "message": "That location detail was false; forget it.",
        },
        target_id=str(existing["id"]),
    )

    apply_validated_memory_analysis_v3(batch, analysis, extractor_model="test-model")
    retracted = storage.get_agent_memory(str(existing["id"]), USER_ID)

    assert retracted is not None
    assert retracted["status"] == "retracted"
    assert retracted["updated_at"] > existing["updated_at"]


def test_rejects_unknown_or_repeated_lifecycle_target() -> None:
    existing = _memory()
    batch = _batch("I do not live there now.")
    operation = {
        "operation": "retract",
        "target_memory_id": "another-users-memory",
        "evidence_message_indexes": [2],
    }

    unknown = validate_memory_analysis_v3(
        {
            "decision": "propose",
            "operations": [operation],
            "handoff": {
                "summary": "",
                "active_people": [],
                "active_topics": [],
                "unresolved_references": [],
            },
        },
        batch=batch,
        existing_memory_ids={str(existing["id"])},
    )

    assert unknown.valid
    assert unknown.operations == ()
    assert "supplied active memory" in " ".join(unknown.dropped)
    repeated_raw = {
        "decision": "propose",
        "operations": [
            {
                "operation": "retract",
                "target_memory_id": existing["id"],
                "evidence_message_indexes": [2],
            },
            {
                "operation": "retract",
                "target_memory_id": existing["id"],
                "evidence_message_indexes": [2],
            },
        ],
        "handoff": {
            "summary": "",
            "active_people": [],
            "active_topics": [],
            "unresolved_references": [],
        },
    }
    repeated = validate_memory_analysis_v3(
        repeated_raw,
        batch=batch,
        existing_memory_ids={str(existing["id"])},
    )

    # The first retract stands; the repeat is dropped.
    assert repeated.valid
    assert len(repeated.operations) == 1
    assert "targeted only once" in " ".join(repeated.dropped)


def test_exact_duplicate_add_reinforces_instead_of_creating_second_memory() -> None:
    existing = _memory()
    batch = _batch("I still live in Bengaluru.")
    operation = {
        "operation": "add",
        "memory_kind": "semantic",
        "purposes": ["profile"],
        "key": "HOME.LOCATION",
        "value": "Bengaluru",
        "sensitivity": "standard",
        "confidence": 0.9,
        "importance": 0.7,
        "occurred_at": None,
        "valid_from": None,
        "valid_until": None,
        "evidence_message_indexes": [2],
    }
    raw = {
        "decision": "propose",
        "operations": [operation],
        "handoff": {
            "summary": "",
            "active_people": [],
            "active_topics": [],
            "unresolved_references": [],
        },
    }
    analysis = validate_memory_analysis_v3(raw, batch=batch)
    assert analysis.valid, analysis.errors

    apply_validated_memory_analysis_v3(batch, analysis, extractor_model="test-model")
    memories = storage.list_agent_memories(USER_ID)

    assert len(memories) == 1
    assert memories[0]["id"] == existing["id"]
    assert len(memories[0]["evidence"]) == 2


def test_retry_is_idempotent_for_lifecycle_operation() -> None:
    existing = _memory()
    batch, analysis = _analysis(
        {
            "operation": "reinforce",
            "target_memory_id": existing["id"],
            "confidence": 0.9,
            "importance": 0.7,
            "evidence_message_indexes": [2],
            "message": "Bengaluru remains my home.",
        },
        target_id=str(existing["id"]),
    )

    first = apply_validated_memory_analysis_v3(batch, analysis, extractor_model="test-model")
    retry = apply_validated_memory_analysis_v3(batch, analysis, extractor_model="test-model")

    assert not first.idempotent
    assert retry.idempotent
    assert len(storage.get_agent_memory(str(existing["id"]), USER_ID)["evidence"]) == 2


def test_conflicting_adds_roll_back_the_complete_batch() -> None:
    storage.save_conversation(
        {
            "id": CONVERSATION_ID,
            "status": "active",
            "messages": [{"role": "user", "content": "I now live in Pune."}],
        },
        USER_ID,
    )
    batch = build_memory_batch(
        conversation_id=CONVERSATION_ID,
        user_id=USER_ID,
        messages=[{"role": "user", "content": "I now live in Pune."}],
    )
    assert batch is not None
    base = {
        "operation": "add",
        "memory_kind": "semantic",
        "purposes": ["profile"],
        "key": "home.location",
        "sensitivity": "standard",
        "confidence": 0.9,
        "importance": 0.7,
        "occurred_at": None,
        "valid_from": None,
        "valid_until": None,
        "evidence_message_indexes": [0],
    }
    raw = {
        "decision": "propose",
        "operations": [
            {**base, "value": "Pune"},
            {**base, "value": "Mumbai"},
        ],
        "handoff": {
            "summary": "",
            "active_people": [],
            "active_topics": [],
            "unresolved_references": [],
        },
    }
    analysis = validate_memory_analysis_v3(raw, batch=batch)
    assert analysis.valid, analysis.errors

    with pytest.raises(ValueError, match="requires supersede"):
        apply_validated_memory_analysis_v3(
            batch,
            analysis,
            extractor_model="test-model",
        )

    assert storage.list_agent_memories(USER_ID) == []
