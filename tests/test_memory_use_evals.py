"""Protects end-to-end scenarios for safe, natural use of V3 memories."""

from __future__ import annotations

import storage

from agent.evals.memory.use import MEMORY_USE_SCENARIOS, setup_memory_use_sample
from scripts.evals.run_behavior_evals import _selected_scenarios


def setup_function() -> None:
    storage.reset_db()


def test_catalogue_covers_relevance_privacy_correction_and_authorization() -> None:
    tags = {tag for scenario in MEMORY_USE_SCENARIOS for tag in scenario.tags}

    assert {"relevant", "irrelevant", "privacy", "correction", "authorization", "expiry"} <= tags
    assert len({scenario.id for scenario in MEMORY_USE_SCENARIOS}) == len(MEMORY_USE_SCENARIOS)
    assert all(scenario.turns[0].expectation.rubric for scenario in MEMORY_USE_SCENARIOS)


def test_scenario_set_selects_memory_use_cases_without_companion_cases() -> None:
    selected = _selected_scenarios(None, scenario_set="memory_use")

    assert selected == MEMORY_USE_SCENARIOS
    assert _selected_scenarios(
        ["current_message_overrides_old_memory"],
        scenario_set="memory_use",
    )[0].id == "current_message_overrides_old_memory"


def test_sample_setup_seeds_traceable_memory_with_declared_permissions() -> None:
    scenario = next(
        item
        for item in MEMORY_USE_SCENARIOS
        if item.id == "exclude_disallowed_and_highly_sensitive_memory"
    )
    user_id = "memory-use-user"
    conversation_id = "memory-use-conversation"
    storage.save_conversation(
        {
            "id": conversation_id,
            "user_id": user_id,
            "status": "active",
            "messages": [],
        },
        user_id,
    )

    setup_memory_use_sample(scenario, user_id, conversation_id)
    memories = storage.list_agent_memories(user_id)

    assert len(memories) == 2
    health = next(memory for memory in memories if memory["key"] == "health.diagnosis")
    matching = next(memory for memory in memories if memory["key"] == "partner.smoking")
    assert health["sensitivity"] == "highly_sensitive"
    assert matching["allowed_uses"] == ["matching"]
    assert health["evidence"][0]["exact_quote"] == "I have bipolar disorder."
    assert matching["evidence"][0]["exact_quote"] == "Smoking is a dating dealbreaker for me."
    assert matching["evidence"][0]["message_index"] == 0
    assert health["evidence"][0]["conversation_id"] != conversation_id
