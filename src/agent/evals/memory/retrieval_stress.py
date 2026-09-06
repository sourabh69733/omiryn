"""Builds and grades deterministic stress fixtures for reply-memory retrieval."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from agent.memory_engine.memories import retrieve_agent_memories_for_reply


RETRIEVAL_STRESS_MEMORY_COUNT = 100
RETRIEVAL_STRESS_LIMIT = 5
RETRIEVAL_STRESS_QUERY = (
    "Help me plan how to talk to Riya about our relaxed Mysuru trip, "
    "one question at a time."
)


@dataclass(frozen=True)
class RetrievalFixtureMemory:
    """One synthetic memory plus the evaluator-only truth used to grade it."""

    key: str
    value: Any
    kind: str
    purposes: tuple[str, ...]
    relevant: bool = False
    allowed_uses: tuple[str, ...] = ("reply_context",)
    sensitivity: str = "standard"
    expires: str = "future"
    confidence: float = 0.55
    importance: float = 0.35


def build_retrieval_stress_fixture() -> tuple[RetrievalFixtureMemory, ...]:
    """Return exactly 100 deterministic memories with known retrieval truth."""
    relevant = (
        RetrievalFixtureMemory(
            key="person.riya.location",
            value="Mysuru",
            kind="semantic",
            purposes=("personalization",),
            relevant=True,
            confidence=0.98,
            importance=0.9,
        ),
        RetrievalFixtureMemory(
            key="travel.preference",
            value="Prefers relaxed trips",
            kind="semantic",
            purposes=("personalization",),
            relevant=True,
            confidence=0.96,
            importance=0.88,
        ),
        RetrievalFixtureMemory(
            key="trip.riya.mysuru",
            value="The user and Riya are planning a relaxed Mysuru trip",
            kind="episodic",
            purposes=("personalization",),
            relevant=True,
            confidence=0.96,
            importance=0.92,
        ),
        RetrievalFixtureMemory(
            key="relationship.riya",
            value="Conversations with Riya usually feel easy",
            kind="relationship",
            purposes=("personalization",),
            relevant=True,
            confidence=0.95,
            importance=0.9,
        ),
        RetrievalFixtureMemory(
            key="conversation.style",
            value="When discussing Riya, ask one question at a time",
            kind="procedural",
            purposes=("personalization",),
            relevant=True,
            confidence=0.98,
            importance=0.95,
        ),
    )
    policy_traps = (
        RetrievalFixtureMemory(
            key="trip.riya.mysuru.old",
            value="An expired Mysuru plan with Riya",
            kind="episodic",
            purposes=("personalization",),
            expires="past",
            confidence=1.0,
            importance=1.0,
        ),
        RetrievalFixtureMemory(
            key="person.riya.location.old",
            value="Mysuru",
            kind="semantic",
            purposes=("personalization",),
            expires="past",
            confidence=1.0,
            importance=1.0,
        ),
        RetrievalFixtureMemory(
            key="health.riya.private",
            value="Highly sensitive information about Riya and the Mysuru trip",
            kind="relationship",
            purposes=("personalization",),
            sensitivity="highly_sensitive",
            confidence=1.0,
            importance=1.0,
        ),
        RetrievalFixtureMemory(
            key="health.user.private",
            value="Highly sensitive travel health detail for Mysuru",
            kind="semantic",
            purposes=("profile",),
            sensitivity="highly_sensitive",
            confidence=1.0,
            importance=1.0,
        ),
        RetrievalFixtureMemory(
            key="matching.riya.preference",
            value="Riya matches a stated partner preference",
            kind="semantic",
            purposes=("matching",),
            allowed_uses=("matching",),
            confidence=1.0,
            importance=1.0,
        ),
    )
    kinds = ("semantic", "episodic", "relationship", "procedural")
    noise = tuple(
        RetrievalFixtureMemory(
            key=f"fixture.noise.{kinds[index % len(kinds)]}.{index:03d}",
            value=f"Unrelated archive marker {index:03d}",
            kind=kinds[index % len(kinds)],
            purposes=("profile",) if index % 2 == 0 else ("personalization",),
        )
        for index in range(90)
    )
    fixture = relevant + policy_traps + noise
    if len(fixture) != RETRIEVAL_STRESS_MEMORY_COUNT:
        raise AssertionError("retrieval stress fixture must contain exactly 100 memories")
    return fixture


def run_retrieval_stress_evaluation(
    *,
    now: datetime | None = None,
    user_id: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Seed the fixture, call production retrieval, and return a report payload."""
    from storage import create_agent_memory, save_conversation

    evaluated_at = now or datetime.now(UTC)
    owner_id = user_id or f"retrieval-eval-{uuid4()}"
    source_conversation_id = conversation_id or f"retrieval-eval-{uuid4()}"
    fixture = build_retrieval_stress_fixture()
    save_conversation(
        {
            "id": source_conversation_id,
            "status": "active",
            "messages": [
                {"role": "user", "content": _evidence_quote(item)} for item in fixture
            ],
        },
        owner_id,
    )

    stored_by_id: dict[str, RetrievalFixtureMemory] = {}
    for message_index, item in enumerate(fixture):
        stored = create_agent_memory(
            _storage_payload(
                item,
                user_id=owner_id,
                conversation_id=source_conversation_id,
                message_index=message_index,
                now=evaluated_at,
            )
        )
        stored_by_id[str(stored["id"])] = item

    selected = retrieve_agent_memories_for_reply(
        owner_id,
        RETRIEVAL_STRESS_QUERY,
        limit=RETRIEVAL_STRESS_LIMIT,
        now=evaluated_at,
    )
    selected_ids = {str(item["id"]) for item in selected}
    relevant_ids = {
        memory_id for memory_id, item in stored_by_id.items() if item.relevant
    }
    policy_trap_ids = {
        memory_id
        for memory_id, item in stored_by_id.items()
        if item.expires == "past"
        or item.sensitivity == "highly_sensitive"
        or "reply_context" not in item.allowed_uses
    }
    retrieved_relevant = relevant_ids & selected_ids
    irrelevant_ids = selected_ids - relevant_ids
    violations = selected_ids & policy_trap_ids
    selected_context = json.dumps(
        [
            {"kind": item["kind"], "key": item["key"], "value": item["value"]}
            for item in selected
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    recall = len(retrieved_relevant) / len(relevant_ids)
    precision = len(retrieved_relevant) / len(selected_ids) if selected_ids else 0.0
    failures = []
    if recall < 1.0:
        failures.append("Not every relevant memory was retrieved.")
    if irrelevant_ids:
        failures.append("Irrelevant memories leaked into the bounded reply context.")
    if violations:
        failures.append("A policy-ineligible memory was retrieved.")
    if len(selected) > RETRIEVAL_STRESS_LIMIT:
        failures.append("The reply memory limit was exceeded.")

    return {
        "stage": "memory_retrieval_stress_eval",
        "passed": not failures,
        "judges": ["deterministic retrieval truth"],
        "companion": {
            "agent_name": "canonical memory retrieval",
            "provider": "local",
            "model": "deterministic",
            "prompt_version": "not applicable",
        },
        "summary": {
            "total": 1,
            "passed": int(not failures),
            "failed": int(bool(failures)),
            "candidate_count": len(fixture),
            "selected_count": len(selected),
        },
        "scenario": {
            "scenario_id": "hundred_memory_policy_and_relevance",
            "query": RETRIEVAL_STRESS_QUERY,
            "candidate_count": len(fixture),
            "expected_relevant_count": len(relevant_ids),
            "policy_trap_count": len(policy_trap_ids),
            "metrics": {
                "target_recall": round(recall, 4),
                "precision_at_k": round(precision, 4),
                "irrelevant_selected_count": len(irrelevant_ids),
                "policy_violation_count": len(violations),
                "selected_count": len(selected),
                "selection_limit": RETRIEVAL_STRESS_LIMIT,
                "selected_payload_chars": len(selected_context),
                "rough_selected_payload_tokens": (len(selected_context) + 3) // 4,
            },
            "expected_relevant_keys": sorted(
                stored_by_id[memory_id].key for memory_id in relevant_ids
            ),
            "selected_memories": [
                {
                    "key": item["key"],
                    "kind": item["kind"],
                    "value": item["value"],
                    "relevant": str(item["id"]) in relevant_ids,
                    "policy_eligible": str(item["id"]) not in policy_trap_ids,
                }
                for item in selected
            ],
            "failures": failures,
        },
    }


def _storage_payload(
    item: RetrievalFixtureMemory,
    *,
    user_id: str,
    conversation_id: str,
    message_index: int,
    now: datetime,
) -> dict[str, Any]:
    valid_until = now - timedelta(seconds=1) if item.expires == "past" else None
    return {
        "user_id": user_id,
        "kind": item.kind,
        "purposes": list(item.purposes),
        "key": item.key,
        "value": item.value,
        "allowed_uses": list(item.allowed_uses),
        "status": "active",
        "sensitivity": item.sensitivity,
        "confidence": item.confidence,
        "importance": item.importance,
        "valid_until": valid_until.isoformat() if valid_until else None,
        "evidence": [
            {
                "conversation_id": conversation_id,
                "message_index": message_index,
                "exact_quote": _evidence_quote(item),
                "observed_at": (now - timedelta(days=1)).isoformat(),
            }
        ],
    }


def _evidence_quote(item: RetrievalFixtureMemory) -> str:
    return f"Synthetic retrieval fixture evidence for {item.key}."


__all__ = [
    "RETRIEVAL_STRESS_LIMIT",
    "RETRIEVAL_STRESS_MEMORY_COUNT",
    "RETRIEVAL_STRESS_QUERY",
    "RetrievalFixtureMemory",
    "build_retrieval_stress_fixture",
    "run_retrieval_stress_evaluation",
]
