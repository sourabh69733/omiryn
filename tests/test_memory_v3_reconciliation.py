"""Verifies bounded related-memory selection before V3 lifecycle decisions."""

from unittest.mock import patch

from agent.cognition.background.service import _existing_memory_context
from agent.memory_engine.memories.reconciliation import select_reconciliation_candidates


def _memory(memory_id: str, key: str, value: object, **changes: object) -> dict[str, object]:
    memory = {
        "id": memory_id,
        "kind": "semantic",
        "purposes": ["profile"],
        "key": key,
        "value": value,
        "status": "active",
        "sensitivity": "standard",
        "confidence": 0.8,
        "importance": 0.6,
        "updated_at": "2026-09-01T10:00:00+00:00",
    }
    memory.update(changes)
    return memory


def test_related_older_memory_outranks_unrelated_recent_memory() -> None:
    memories = [
        _memory(
            "recent-music",
            "favorite_music",
            "Jazz",
            updated_at="2026-09-09T10:00:00+00:00",
        ),
        _memory(
            "older-location",
            "home_location",
            "Bengaluru",
            updated_at="2026-06-01T10:00:00+00:00",
        ),
    ]

    selected = select_reconciliation_candidates(
        memories,
        "I moved away from Bengaluru and now live in Pune.",
        limit=1,
    )

    assert [memory["id"] for memory in selected] == ["older-location"]


def test_selection_keeps_relevant_inactive_history_for_reconciliation() -> None:
    memories = [
        _memory("active", "food_preference", "pasta"),
        _memory(
            "retracted",
            "partner_values",
            "adventure",
            status="retracted",
        ),
    ]

    selected = select_reconciliation_candidates(
        memories,
        "I value adventure in a partner again.",
        limit=1,
    )

    assert [memory["id"] for memory in selected] == ["retracted"]


def test_selection_keeps_fields_needed_for_lifecycle_reasoning() -> None:
    memory = _memory(
        "relationship",
        "former_roommate_conflict",
        {"pattern": "avoided money talks", "outcome": "arguments"},
        kind="relationship",
        purposes=["personalization"],
        sensitivity="sensitive",
        importance=0.9,
    )

    selected = select_reconciliation_candidates([memory], "My old roommate contacted me.")

    assert selected == [memory]


def test_semantic_similarity_finds_cross_language_reconciliation_candidate() -> None:
    relevant = _memory("calm-partner", "partner_temperament", "prefers a calm partner")
    unrelated = _memory("food", "food_preference", "likes pasta", importance=1.0)
    query_embedding = {
        "provider": "deepinfra",
        "model": "multilingual",
        "dimensions": 2,
        "values": [1.0, 0.0],
    }
    embeddings = {
        "calm-partner": {**query_embedding, "memory_id": "calm-partner"},
        "food": {**query_embedding, "memory_id": "food", "values": [0.0, 1.0]},
    }

    selected = select_reconciliation_candidates(
        [unrelated, relevant],
        "मुझे शांत साथी पसंद है",
        limit=1,
        query_embedding=query_embedding,
        embeddings_by_memory_id=embeddings,
    )

    assert selected[0]["id"] == "calm-partner"


def test_cognition_context_loads_matching_memory_embedding_versions() -> None:
    query_embedding = {
        "provider": "deepinfra",
        "model": "multilingual",
        "dimensions": 2,
        "values": [1.0, 0.0],
    }
    memories = [
        _memory("food", "food_preference", "likes pasta", importance=1.0),
        _memory("calm", "partner_temperament", "prefers a calm partner"),
    ]
    stored_embeddings = [
        {**query_embedding, "memory_id": "food", "values": [0.0, 1.0]},
        {**query_embedding, "memory_id": "calm"},
    ]

    with (
        patch(
            "agent.cognition.background.service.list_agent_memories",
            return_value=memories,
        ),
        patch(
            "agent.cognition.background.service.list_agent_memory_embeddings",
            return_value=stored_embeddings,
        ),
    ):
        context = _existing_memory_context(
            "user-1",
            3,
            "मुझे शांत साथी पसंद है",
            query_embedding=query_embedding,
        )

    assert context[0]["id"] == "calm"


def test_cognition_context_uses_related_candidates_instead_of_first_rows() -> None:
    unrelated = [
        _memory(f"unrelated-{index}", f"topic_{index}", f"value {index}")
        for index in range(8)
    ]
    related = _memory(
        "related-location",
        "home_location",
        "Bengaluru",
        sensitivity="sensitive",
        importance=0.95,
    )

    with patch(
        "agent.cognition.background.service.list_agent_memories",
        return_value=[*unrelated, related],
    ):
        context = _existing_memory_context(
            "user-1",
            3,
            "I moved away from Bengaluru.",
        )

    selected = next(memory for memory in context if memory["id"] == "related-location")
    assert selected["sensitivity"] == "sensitive"
    assert selected["importance"] == 0.95


def test_cognition_context_marks_only_active_memories_as_targetable() -> None:
    memories = [
        _memory("active", "home_location", "Pune"),
        _memory("retracted", "home_location", "Bengaluru", status="retracted"),
    ]

    with patch(
        "agent.cognition.background.service.list_agent_memories",
        return_value=memories,
    ):
        context = _existing_memory_context(
            "user-1",
            3,
            "I live in Bengaluru again, not Pune.",
        )

    by_id = {memory["id"]: memory for memory in context}
    assert by_id["active"]["status"] == "active"
    assert by_id["active"]["targetable"] is True
    assert by_id["retracted"]["status"] == "retracted"
    assert by_id["retracted"]["targetable"] is False
