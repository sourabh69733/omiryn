"""Verifies safe, bounded retrieval of canonical v3 memories for replies."""

from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import storage
from agent.context_engine.assembly.sources import build_reply_context_sources


USER_ID = "memory-v3-retrieval-user"
CONVERSATION_ID = "memory-v3-retrieval-conversation"
NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def setup_function() -> None:
    storage.reset_db()
    storage.save_conversation(
        {
            "id": CONVERSATION_ID,
            "status": "active",
            "messages": [{"role": "user", "content": "seed"}],
        },
        USER_ID,
    )


def test_retrieval_excludes_inactive_disallowed_and_highly_sensitive_memories() -> None:
    allowed = _save_memory(key="home.location", value="Pune")
    _save_memory(key="private.health", value="diagnosis", sensitivity="highly_sensitive")
    _save_memory(key="matching.only", value="vegetarian", allowed_uses=["matching"])
    _save_memory(key="old.location", value="Bengaluru", status="superseded")

    selected = _retrieve("What is my home location in Pune?")

    assert [memory["id"] for memory in selected] == [allowed["id"]]


def test_retrieval_excludes_memory_after_valid_until() -> None:
    expired = _save_memory(
        key="home.location",
        value="Bengaluru",
        valid_until=NOW - timedelta(seconds=1),
    )

    selected = _retrieve("What is my home location in Pune?")

    assert expired["id"] not in {memory["id"] for memory in selected}


def test_retrieval_includes_memory_before_valid_until() -> None:
    current = _save_memory(
        key="home.location",
        value="Pune",
        valid_until=NOW + timedelta(days=1),
    )

    selected = _retrieve("What is my home location in Pune?")

    assert current["id"] in {memory["id"] for memory in selected}


def test_retrieval_excludes_memory_before_valid_from() -> None:
    future = _save_memory(
        key="home.location",
        value="Pune",
        valid_from=NOW + timedelta(seconds=1),
    )

    selected = _retrieve("What is my home location in Pune?")

    assert future["id"] not in {memory["id"] for memory in selected}


def test_retrieval_returns_no_unrelated_content_memories() -> None:
    _save_memory(key="favorite.dessert", value="tiramisu")
    _save_memory(
        key="relationship.riya",
        value={"person": "Riya", "pattern": "easy conversations"},
        kind="relationship",
        purposes=["personalization"],
    )

    assert _retrieve("Why did my deployment fail?") == []


def test_retrieval_keeps_procedural_guidance_without_topic_overlap() -> None:
    procedural = _save_memory(
        key="conversation.style",
        value="Ask one question at a time",
        kind="procedural",
        purposes=["personalization"],
    )

    selected = _retrieve("Why did my deployment fail?")

    assert [memory["id"] for memory in selected] == [procedural["id"]]


def test_retrieval_is_kind_aware_and_ranks_relevant_memory_first() -> None:
    unrelated = _save_memory(
        key="food.preference",
        value="spicy food",
        confidence=1.0,
        importance=1.0,
    )
    relevant = _save_memory(
        key="relationship.riya",
        value={"person": "Riya", "pattern": "feels understood by her"},
        kind="relationship",
        purposes=["personalization"],
        confidence=0.8,
        importance=0.7,
    )
    procedural = _save_memory(
        key="conversation.style",
        value="Do not ask many questions at once",
        kind="procedural",
        purposes=["personalization"],
    )

    selected = _retrieve("Riya called me again")

    ids = [memory["id"] for memory in selected]
    assert relevant["id"] in ids
    assert unrelated["id"] not in ids
    assert procedural["id"] in ids


def test_retrieval_limits_each_kind_and_total_context() -> None:
    for index in range(4):
        _save_memory(
            key=f"profile.fact.{index}",
            value=f"fact {index}",
            importance=1.0 - index / 10,
        )
    for index in range(3):
        _save_memory(
            key=f"event.{index}",
            value=f"event {index}",
            kind="episodic",
            purposes=["personalization"],
            importance=1.0 - index / 10,
        )

    selected = _retrieve("Tell me about my profile facts and events", limit=5)

    assert len(selected) <= 5
    assert sum(item["kind"] == "semantic" for item in selected) == 2
    assert sum(item["kind"] == "episodic" for item in selected) == 1


def test_context_uses_v3_memories_only_for_v3_pipeline() -> None:
    memory = _save_memory(
        key="relationship.riya",
        value={"person": "Riya", "experience": "easy conversations"},
        kind="relationship",
        purposes=["personalization"],
    )

    with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3"}, clear=False):
        v3_sources = build_reply_context_sources(
            CONVERSATION_ID,
            None,
            "Riya messaged me",
            USER_ID,
        )
    with patch.dict(
        os.environ,
        {"AGENT_PIPELINE_VERSION": "v2", "AGENT_ROLLOUT": "live"},
        clear=False,
    ):
        v2_sources = build_reply_context_sources(
            CONVERSATION_ID,
            None,
            "Riya messaged me",
            USER_ID,
        )

    v3_memory_source = next(
        source for source in v3_sources if source["source_type"] == "agent_memories_v3"
    )
    assert memory["id"] in v3_memory_source["metadata"]["memory_ids"]
    assert "Riya" in v3_memory_source["content"]
    assert all(source["source_type"] != "agent_memories_v3" for source in v2_sources)


def test_context_shows_event_and_expiry_dates_to_the_model() -> None:
    _save_memory(
        key="relationship.riya",
        value="Met Riya at a wedding",
        kind="episodic",
        purposes=["personalization"],
        occurred_at=datetime(2025, 3, 14, 10, 0, tzinfo=UTC),
        valid_until=datetime.now(UTC) + timedelta(days=30),
    )

    with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3"}, clear=False):
        sources = build_reply_context_sources(CONVERSATION_ID, None, "Riya wedding", USER_ID)

    content = next(s for s in sources if s["source_type"] == "agent_memories_v3")["content"]
    assert "happened Fri 14 Mar 2025 (" in content
    assert "told you Tue 1 Sep 2026 (" in content
    assert "valid until" in content
    assert "not present past events as current" in content


def _memory_context(user_text: str) -> str:
    with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3"}, clear=False):
        sources = build_reply_context_sources(CONVERSATION_ID, None, user_text, USER_ID)
    return next(s for s in sources if s["source_type"] == "agent_memories_v3")["content"]


def test_context_shows_the_memory_as_a_plain_sentence() -> None:
    saved = _save_memory(
        key="pets.dog",
        value={"name": "Bruno", "breed": "beagle"},
        statement="Has a beagle called Bruno.",
    )

    assert saved["statement"] == "Has a beagle called Bruno."
    content = _memory_context("how is my dog Bruno")
    assert "- Has a beagle called Bruno. (told you" in content
    assert "semantic" not in content and "pets.dog" not in content


def test_memory_without_a_statement_still_reads_as_text() -> None:
    _save_memory(key="pets.dog", value={"name": "Bruno", "breed": "beagle", "age": None})

    content = _memory_context("how is my dog Bruno")
    assert "- Pets dog: name: Bruno; breed: beagle (told you" in content


def test_statement_is_searchable() -> None:
    saved = _save_memory(key="misc.item", value="x", statement="Plays the tabla on weekends.")

    assert saved["id"] in {memory["id"] for memory in _retrieve("I practised tabla today")}


def _retrieve(user_text: str, *, limit: int = 5) -> list[dict[str, object]]:
    package = importlib.import_module("agent.memory_engine.memories")
    function = getattr(package, "retrieve_agent_memories_for_reply", None)
    assert callable(function), "v3 reply-memory retrieval is missing"
    return function(USER_ID, user_text, limit=limit, now=NOW)


def _save_memory(
    *,
    key: str,
    value: object,
    kind: str = "semantic",
    purposes: list[str] | None = None,
    allowed_uses: list[str] | None = None,
    sensitivity: str = "standard",
    status: str = "active",
    confidence: float = 0.9,
    importance: float = 0.8,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    occurred_at: datetime | None = None,
    statement: str | None = None,
) -> dict[str, object]:
    observed_at = (NOW - timedelta(days=1)).isoformat()
    return storage.create_agent_memory(
        {
            "user_id": USER_ID,
            "kind": kind,
            "purposes": purposes or ["profile"],
            "key": key,
            "value": value,
            "statement": statement,
            "allowed_uses": allowed_uses or ["reply_context"],
            "status": status,
            "sensitivity": sensitivity,
            "confidence": confidence,
            "importance": importance,
            "occurred_at": occurred_at.isoformat() if occurred_at else None,
            "valid_from": valid_from.isoformat() if valid_from else None,
            "valid_until": valid_until.isoformat() if valid_until else None,
            "evidence": [
                {
                    "conversation_id": CONVERSATION_ID,
                    "message_index": 0,
                    "exact_quote": f"Evidence for {key}",
                    "observed_at": observed_at,
                }
            ],
        }
    )
