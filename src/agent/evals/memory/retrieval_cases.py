"""Deterministic case suite for reply-memory retrieval beyond the 100-memory stress run.

Each case seeds a few memories for its own user, calls production retrieval with the
current user message only (what live keyword retrieval sees), and grades the selection.
Cases marked `needs_semantic` describe meaning-level recall that keyword matching cannot
be expected to solve; they measure how far embeddings would have to carry.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from agent.memory_engine.memories import retrieve_agent_memories_for_reply
from agent.memory_engine.memories.ranking import (
    embedding_similarity,
    searchable_memory_text,
    text_relevance,
)
from agent.memory_engine.memories.embeddings import (
    embed_memory_query,
    index_agent_memories,
    memory_embedding_target,
    memory_query_text,
)


@dataclass(frozen=True)
class CaseMemory:
    key: str
    value: Any
    kind: str = "semantic"
    status: str = "active"
    purposes: tuple[str, ...] = ("personalization",)


@dataclass(frozen=True)
class RetrievalCase:
    case_id: str
    description: str
    query: str
    memories: tuple[CaseMemory, ...]
    expected_keys: frozenset[str] = frozenset()
    forbidden_keys: frozenset[str] = frozenset()
    needs_semantic: bool = False
    history: tuple[dict[str, str], ...] = ()
    tags: tuple[str, ...] = field(default_factory=tuple)


RIYA = CaseMemory("relationship.riya", "Conversations with Riya usually feel easy", "relationship")
NOISE = (
    CaseMemory("food.preference", "spicy food"),
    CaseMemory("hobby.weekend", "trekking on weekends", "episodic"),
)

RETRIEVAL_CASES: tuple[RetrievalCase, ...] = (
    RetrievalCase(
        case_id="follow_up_pronoun",
        description="A follow-up that names no one must still recall the person just discussed.",
        query="what about her?",
        memories=(RIYA, *NOISE),
        expected_keys=frozenset({"relationship.riya"}),
        forbidden_keys=frozenset({"food.preference", "hobby.weekend"}),
        needs_semantic=True,
        history=(
            {"role": "user", "content": "Riya called me again yesterday"},
            {"role": "assistant", "content": "How did that call with Riya feel?"},
        ),
        tags=("follow_up",),
    ),
    RetrievalCase(
        case_id="unrelated_message_returns_nothing",
        description="A technical message must not pull personal memories.",
        query="Why did my deployment fail?",
        memories=(RIYA, *NOISE),
        forbidden_keys=frozenset({"relationship.riya", "food.preference", "hobby.weekend"}),
        tags=("precision",),
    ),
    RetrievalCase(
        case_id="superseded_memory_not_recalled",
        description="Only the current city is recalled; the corrected one stays out.",
        query="Tell me about my home city",
        memories=(
            CaseMemory("home.city", "Pune", status="superseded"),
            CaseMemory("home.city", "Bengaluru"),
        ),
        expected_keys=frozenset({"home.city"}),
        forbidden_keys=frozenset(),
        tags=("correction",),
    ),
    RetrievalCase(
        case_id="english_paraphrase",
        description="The user says 'job'; the memory stores 'nurse' under a 'career' key.",
        query="my job is exhausting me",
        memories=(CaseMemory("career.role", "nurse"), *NOISE),
        expected_keys=frozenset({"career.role"}),
        forbidden_keys=frozenset({"food.preference", "hobby.weekend"}),
        needs_semantic=True,
        tags=("paraphrase",),
    ),
    RetrievalCase(
        case_id="hinglish_shared_name",
        description="Hinglish message that shares a name with the memory.",
        query="Riya kal phir call kar rahi thi",
        memories=(RIYA, *NOISE),
        expected_keys=frozenset({"relationship.riya"}),
        tags=("hinglish",),
    ),
    RetrievalCase(
        case_id="hinglish_paraphrase",
        description="Hinglish evening plan should recall a stated quiet-evenings preference.",
        query="aaj shaam ko kya karun?",
        memories=(CaseMemory("lifestyle.evenings", "Prefers quiet evenings at home"), *NOISE),
        expected_keys=frozenset({"lifestyle.evenings"}),
        forbidden_keys=frozenset({"food.preference", "hobby.weekend"}),
        needs_semantic=True,
        tags=("hinglish", "paraphrase"),
    ),
)


def run_retrieval_cases_evaluation(
    *, now: datetime | None = None, semantic: bool = True
) -> dict[str, Any]:
    """Seed each case, run production retrieval, and return a report payload.

    With `semantic`, memories and queries are embedded through the configured model,
    mirroring live turns; otherwise retrieval is keyword-only.
    """
    evaluated_at = now or datetime.now(UTC)
    use_embeddings = semantic and memory_embedding_target() is not None
    results = [_run_case(case, evaluated_at, use_embeddings) for case in RETRIEVAL_CASES]
    keyword_cases = [result for result in results if not result["needs_semantic"]]
    semantic_cases = [result for result in results if result["needs_semantic"]]
    # Semantic cases only gate the run when embeddings are actually in use.
    gating = results if use_embeddings else keyword_cases
    passed = all(result["passed"] for result in gating)
    return {
        "stage": "memory_retrieval_cases_eval",
        "passed": passed,
        "judges": ["deterministic retrieval truth"],
        "companion": {
            "agent_name": "canonical memory retrieval",
            "provider": "local",
            "model": "deterministic",
            "prompt_version": "not applicable",
        },
        "retrieval_mode": "semantic" if use_embeddings else "keyword_only",
        "summary": {
            "total": len(results),
            "passed": sum(result["passed"] for result in results),
            "failed": sum(not result["passed"] for result in results),
            "keyword_passed": sum(result["passed"] for result in keyword_cases),
            "keyword_total": len(keyword_cases),
            "semantic_passed": sum(result["passed"] for result in semantic_cases),
            "semantic_total": len(semantic_cases),
        },
        "cases": results,
    }


def _run_case(case: RetrievalCase, now: datetime, use_embeddings: bool) -> dict[str, Any]:
    from storage import create_agent_memory, save_conversation

    user_id = f"retrieval-case-{uuid4()}"
    conversation_id = f"retrieval-case-{uuid4()}"
    save_conversation(
        {
            "id": conversation_id,
            "status": "active",
            "messages": [
                {"role": "user", "content": f"Synthetic evidence for {memory.key}."}
                for memory in case.memories
            ],
        },
        user_id,
    )
    stored = []
    for index, memory in enumerate(case.memories):
        stored.append(create_agent_memory(
            {
                "user_id": user_id,
                "kind": memory.kind,
                "purposes": list(memory.purposes),
                "key": memory.key,
                "value": memory.value,
                "allowed_uses": ["reply_context"],
                "status": memory.status,
                "sensitivity": "standard",
                "confidence": 0.9,
                "importance": 0.7,
                "evidence": [
                    {
                        "conversation_id": conversation_id,
                        "message_index": index,
                        "exact_quote": f"Synthetic evidence for {memory.key}.",
                        "observed_at": (now - timedelta(days=1)).isoformat(),
                    }
                ],
            }
        ))
    query_embedding = None
    if use_embeddings:
        asyncio.run(index_agent_memories([m for m in stored if m["status"] == "active"]))
        query_embedding = asyncio.run(
            embed_memory_query(
                memory_query_text(case.query, list(case.history)),
                conversation_id=conversation_id,
            )
        )
    selected = retrieve_agent_memories_for_reply(
        user_id, case.query, now=now, query_embedding=query_embedding
    )
    scores = _relevance_scores(user_id, stored, case.query, query_embedding)
    selected_keys = {str(item["key"]) for item in selected}
    superseded = {memory.key for memory in case.memories if memory.status != "active"}
    missing = sorted(case.expected_keys - selected_keys)
    leaked = sorted(selected_keys & case.forbidden_keys)
    stale = [
        str(item["value"]) for item in selected if item["status"] != "active"
    ] if superseded else []
    problems = []
    if missing:
        problems.append(f"Not recalled: {', '.join(missing)}")
    if leaked:
        problems.append(f"Wrongly recalled: {', '.join(leaked)}")
    if stale:
        problems.append(f"Inactive memory recalled: {', '.join(stale)}")
    if not case.expected_keys and not case.forbidden_keys and selected:
        problems.append("Nothing should have been recalled.")
    return {
        "case_id": case.case_id,
        "description": case.description,
        "query": case.query,
        "tags": list(case.tags),
        "needs_semantic": case.needs_semantic,
        "passed": not problems,
        "problems": problems,
        "selected": [
            {"key": item["key"], "value": item["value"], "status": item["status"]}
            for item in selected
        ],
        "scores": scores,
    }


def _relevance_scores(
    user_id: str,
    stored: list[dict[str, Any]],
    query: str,
    query_embedding: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Expose raw relevance per memory so the selection floors can be tuned from data."""
    from storage.memory_embeddings import list_agent_memory_embeddings

    active = [memory for memory in stored if memory["status"] == "active"]
    embeddings = (
        {
            str(item["memory_id"]): item
            for item in list_agent_memory_embeddings(user_id, [str(m["id"]) for m in active])
        }
        if query_embedding
        else {}
    )
    rows = []
    for memory in active:
        semantic = embedding_similarity(query_embedding, embeddings.get(str(memory["id"])))
        rows.append(
            {
                "key": memory["key"],
                "lexical": round(text_relevance(query, searchable_memory_text(memory)), 3),
                "semantic": None if semantic is None else round(semantic, 3),
            }
        )
    return rows


__all__ = ["RETRIEVAL_CASES", "RetrievalCase", "run_retrieval_cases_evaluation"]
