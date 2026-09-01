"""Verifies the v3 memory taxonomy, evidence traceability, and time invariants."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from agent.memory_engine.memories import (
    MEMORY_SCHEMA_VERSION,
    MemoryEvidence,
    MemoryKind,
    MemoryPurpose,
    MemoryRecord,
    MemoryStatus,
    MemoryUse,
)


NOW = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def _evidence() -> MemoryEvidence:
    return MemoryEvidence(
        conversation_id="conversation-1",
        message_index=4,
        exact_quote="I build a matchmaking product called Omiryn.",
        observed_at=NOW,
    )


def _memory(**changes: object) -> MemoryRecord:
    memory = MemoryRecord(
        id="memory-1",
        user_id="user-1",
        kind=MemoryKind.SEMANTIC,
        purposes=frozenset({MemoryPurpose.PROFILE}),
        key="work.product",
        value={"name": "Omiryn", "role": "builder"},
        evidence=(_evidence(),),
        created_at=NOW,
        updated_at=NOW,
        allowed_uses=frozenset({MemoryUse.REPLY_CONTEXT}),
    )
    return replace(memory, **changes)


def test_contract_supports_four_memory_kinds_and_separate_purposes() -> None:
    assert {kind.value for kind in MemoryKind} == {
        "semantic",
        "episodic",
        "relationship",
        "procedural",
    }
    assert {purpose.value for purpose in MemoryPurpose} == {
        "profile",
        "matching",
        "personalization",
    }
    assert _memory().schema_version == MEMORY_SCHEMA_VERSION == 3


def test_relationship_memory_is_not_implicitly_allowed_for_matching() -> None:
    memory = _memory(
        kind=MemoryKind.RELATIONSHIP,
        purposes=frozenset({MemoryPurpose.PERSONALIZATION}),
    )

    assert MemoryUse.REPLY_CONTEXT in memory.allowed_uses
    assert MemoryUse.MATCHING not in memory.allowed_uses


def test_evidence_requires_a_message_reference_and_exact_quote() -> None:
    with pytest.raises(ValueError, match="message_id or message_index"):
        replace(_evidence(), message_index=None)

    with pytest.raises(ValueError, match="exact user quote"):
        replace(_evidence(), exact_quote=" ")


def test_memory_requires_evidence_and_bounded_scores() -> None:
    with pytest.raises(ValueError, match="at least one evidence"):
        _memory(evidence=())

    with pytest.raises(ValueError, match="confidence"):
        _memory(confidence=1.1)

    with pytest.raises(ValueError, match="importance"):
        _memory(importance=-0.1)


def test_memory_requires_timezone_aware_ordered_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _memory(updated_at=datetime(2026, 9, 1, 10, 0))

    with pytest.raises(ValueError, match="cannot precede created_at"):
        _memory(updated_at=NOW - timedelta(seconds=1))

    with pytest.raises(ValueError, match="valid_until"):
        _memory(valid_from=NOW, valid_until=NOW - timedelta(seconds=1))


def test_correction_can_link_to_the_memory_it_supersedes() -> None:
    memory = _memory(
        supersedes_memory_id="memory-0",
        updated_at=NOW + timedelta(minutes=1),
    )
    assert memory.supersedes_memory_id == "memory-0"

    with pytest.raises(ValueError, match="cannot supersede itself"):
        _memory(supersedes_memory_id="memory-1")

    historical = _memory(status=MemoryStatus.SUPERSEDED)
    assert historical.status is MemoryStatus.SUPERSEDED
