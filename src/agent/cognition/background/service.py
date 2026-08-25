"""Coordinates one background model call across memory and thread domains."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

from agent.config import agent_pipeline_config
from agent.context_engine.conversation_engine.state import (
    apply_validated_thread_proposal,
    background_thread_candidates,
)
from agent.cognition.background.prompt import background_cognition_prompt
from agent.providers import analyze_background_cognition
from storage import list_data_point_extraction_debug, list_profile_facts
from storage.profile_facts import save_data_point_extraction_debug

from agent.memory_engine.processing.context import DEFAULT_CONTEXT_OVERLAP, build_memory_batch
from agent.memory_engine.processing.application import (
    apply_validated_memory_analysis,
    memory_background_v2_live_writes_enabled,
)
from agent.memory_engine.processing.models import MemoryBatch, MemoryHandoff, MemoryOperation, MemoryProcessingState
from agent.memory_engine.processing.service import (
    claim_processing_batch,
    get_processing_state,
    release_processing_batch,
    save_processing_state,
)
from agent.memory_engine.processing.validation import MemoryAnalysis
from .coordination import interpret_background_cognition


MAX_EXISTING_MEMORIES = 8


def background_cognition_enabled() -> bool:
    return agent_pipeline_config().background_memory_enabled


def background_cognition_threshold() -> int:
    try:
        return max(1, int(os.getenv("MEMORY_BACKGROUND_V2_THRESHOLD", "7")))
    except ValueError:
        return 7


def _pending_background_cognition_batch(
    conversation_id: str,
    user_id: str,
    messages: list[dict[str, object]],
    *,
    state: MemoryProcessingState | None,
) -> MemoryBatch | None:
    """Build the next bounded batch from the durable processing cursor."""
    return build_memory_batch(
        conversation_id=conversation_id,
        user_id=user_id,
        messages=messages,
        state=state,
        context_overlap=_context_overlap(),
        max_meaningful_user_messages=background_cognition_threshold(),
    )


def should_schedule_background_cognition(
    conversation_id: str,
    user_id: str | None,
    messages: list[dict[str, object]],
    quality_valid: bool,
) -> bool:
    """Schedule immediately when the meaningful-message threshold is complete."""
    if not background_cognition_enabled() or not user_id or not quality_valid:
        return False
    batch = _pending_background_cognition_batch(
        conversation_id,
        user_id,
        messages,
        state=get_processing_state(conversation_id, user_id),
    )
    return bool(
        batch
        and batch.meaningful_user_message_count >= background_cognition_threshold()
    )


def should_schedule_idle_background_cognition(
    conversation_id: str,
    user_id: str | None,
    messages: list[dict[str, object]],
    quality_valid: bool,
) -> bool:
    """Debounce only meaningful work that has not reached the normal threshold."""
    if not background_cognition_enabled() or not user_id or not quality_valid:
        return False
    batch = _pending_background_cognition_batch(
        conversation_id,
        user_id,
        messages,
        state=get_processing_state(conversation_id, user_id),
    )
    return bool(
        batch
        and 0
        < batch.meaningful_user_message_count
        < background_cognition_threshold()
    )


async def run_background_cognition(
    conversation_id: str,
    user_id: str,
    messages: list[dict[str, object]],
    model: str | None = None,
) -> dict[str, Any]:
    """Claim and analyze one batch without duplicating its model call."""
    state = get_processing_state(conversation_id, user_id)
    batch = _pending_background_cognition_batch(
        conversation_id,
        user_id,
        messages,
        state=state,
    )
    if batch is None or batch.meaningful_user_message_count == 0:
        return {"status": "no_pending_messages", "operation_count": 0}

    lease_owner = claim_processing_batch(
        conversation_id,
        user_id,
        batch.batch_key,
        expected_processed_index=(
            state.processed_through_message_index if state is not None else -1
        ),
        lease_seconds=_lease_seconds(),
    )
    if lease_owner is None:
        return {
            "status": "already_processing",
            "batch_key": batch.batch_key,
            "operation_count": 0,
        }

    try:
        return await _run_claimed_background_cognition(
            batch=batch,
            state=state,
            model=model,
        )
    finally:
        release_processing_batch(batch.batch_key, user_id, lease_owner)


async def _run_claimed_background_cognition(
    *,
    batch: MemoryBatch,
    state: MemoryProcessingState | None,
    model: str | None,
) -> dict[str, Any]:
    """Run the expensive work after this worker owns the batch lease."""
    conversation_id = batch.conversation_id
    user_id = batch.user_id
    existing_memories = _existing_memory_context(user_id)
    thread_candidates = background_thread_candidates(
        conversation_id,
        user_id,
        " ".join(
            message.content
            for message in batch.new_messages
            if message.role == "user"
        ),
    )
    application_result = None
    thread_application_result = None
    live_attempted = (
        agent_pipeline_config().live_memory_writes
        or agent_pipeline_config().live_thread_writes
    )
    try:
        raw = await analyze_background_cognition(
            background_cognition_prompt(batch, existing_memories, thread_candidates),
            conversation_id=conversation_id,
            model=os.getenv("MEMORY_BACKGROUND_V2_MODEL", "").strip() or model,
            timeout_seconds=_timeout_seconds(),
        )
        cognition = interpret_background_cognition(
            raw,
            batch=batch,
            existing_memory_ids={str(memory["id"]) for memory in existing_memories},
            thread_candidates=thread_candidates,
        )
        analysis = cognition.memory
        if analysis.valid and memory_background_v2_live_writes_enabled():
            try:
                application_result = apply_validated_memory_analysis(batch, analysis)
            except Exception as error:
                _save_shadow_debug_once(
                    batch=batch,
                    decision="live_error",
                    candidate={
                        "model_decision": analysis.decision,
                        "operations": [
                            _operation_dict(operation) for operation in analysis.operations
                        ],
                        "thread_operation": raw.get("thread_operation"),
                        "handoff": _handoff_dict(analysis.handoff),
                    },
                    review={
                        "valid": True,
                        "errors": [f"{type(error).__name__}: {str(error)[:300]}"],
                        "thread_valid": cognition.thread.get("valid", False),
                        "thread_errors": cognition.thread.get("errors", []),
                        "thread_proposal": cognition.thread.get("proposal"),
                        "live_writes": True,
                    },
                    state_version=state.version if state else 0,
                    live_writes=True,
                )
                return {
                    "status": "live_error",
                    "batch_key": batch.batch_key,
                    "operation_count": len(analysis.operations),
                    "thread_operation": cognition.thread_operation,
                    "thread_valid": bool(cognition.thread.get("valid")),
                    "errors": [f"{type(error).__name__}: {str(error)[:300]}"],
                }
        if bool(cognition.thread.get("valid")) and agent_pipeline_config().live_thread_writes:
            thread_application_result = apply_validated_thread_proposal(
                batch_key=batch.batch_key,
                conversation_id=batch.conversation_id,
                user_id=batch.user_id,
                message_index=batch.new_end_message_index,
                proposal=cognition.thread.get("proposal"),
            )
        next_handoff = analysis.handoff if analysis.valid else batch.previous_handoff
        current_state = state or MemoryProcessingState(
            conversation_id=conversation_id,
            user_id=user_id,
        )
        saved_state = save_processing_state(
            replace(
                current_state,
                processed_through_message_index=batch.new_end_message_index,
                last_batch_key=batch.batch_key,
                handoff=next_handoff,
            )
        )
        decision = _result_decision(analysis, application_result, thread_application_result)
        live_writes = application_result is not None or thread_application_result is not None
        _save_shadow_debug_once(
            batch=batch,
            decision=decision,
            candidate={
                "model_decision": analysis.decision,
                "operations": [_operation_dict(operation) for operation in analysis.operations],
                "thread_operation": raw.get("thread_operation"),
                "handoff": _handoff_dict(analysis.handoff),
            },
            review={
                "valid": analysis.valid,
                "errors": list(analysis.errors),
                "combined_valid": cognition.valid,
                "combined_errors": list(cognition.errors),
                "thread_valid": bool(cognition.thread.get("valid")),
                "thread_errors": list(cognition.thread.get("errors") or []),
                "thread_proposal": cognition.thread.get("proposal"),
                "live_writes": live_writes,
                "applied_count": application_result.applied_count if application_result else 0,
                "deferred_count": (
                    application_result.deferred_count if application_result else 0
                ),
                "idempotent": application_result.idempotent if application_result else False,
                "thread_applied_count": (
                    thread_application_result.applied_count if thread_application_result else 0
                ),
                "thread_idempotent": (
                    thread_application_result.idempotent if thread_application_result else False
                ),
            },
            state_version=saved_state.version,
            live_writes=live_writes,
        )
        return {
            "status": decision,
            "batch_key": batch.batch_key,
            "operation_count": len(analysis.operations),
            "thread_operation": cognition.thread_operation,
            "thread_valid": bool(cognition.thread.get("valid")),
            "thread_errors": list(cognition.thread.get("errors") or []),
            "applied_count": application_result.applied_count if application_result else 0,
            "deferred_count": application_result.deferred_count if application_result else 0,
            "idempotent": application_result.idempotent if application_result else False,
            "thread_applied_count": (
                thread_application_result.applied_count if thread_application_result else 0
            ),
            "thread_idempotent": (
                thread_application_result.idempotent if thread_application_result else False
            ),
            "errors": list(analysis.errors),
            "processed_through_message_index": saved_state.processed_through_message_index,
        }
    except Exception as error:
        live_writes = application_result is not None or thread_application_result is not None
        decision = "live_error" if live_attempted else "shadow_error"
        _save_shadow_debug_once(
            batch=batch,
            decision=decision,
            candidate={},
            review={
                "valid": False,
                "errors": [f"{type(error).__name__}: {str(error)[:300]}"],
                "live_writes": live_writes,
            },
            state_version=state.version if state else 0,
            live_writes=live_writes,
        )
        return {
            "status": decision,
            "batch_key": batch.batch_key,
            "operation_count": (
                application_result.applied_count + application_result.deferred_count
                if application_result
                else 0
            ),
            "errors": [f"{type(error).__name__}: {str(error)[:300]}"],
        }


def _existing_memory_context(user_id: str) -> list[dict[str, Any]]:
    memories = list_profile_facts(user_id, statuses={"active"})
    memories.sort(key=lambda memory: str(memory.get("updated_at") or ""), reverse=True)
    return [
        {
            "id": memory["id"],
            "data_point_type": memory["fact_type"],
            "category": memory["category"],
            "key": memory["key"],
            "label": memory["label"],
            "value": memory["value"],
            "confidence": memory["confidence"],
        }
        for memory in memories[:MAX_EXISTING_MEMORIES]
    ]


def _save_shadow_debug_once(
    *,
    batch: MemoryBatch,
    decision: str,
    candidate: dict[str, Any],
    review: dict[str, Any],
    state_version: int,
    live_writes: bool = False,
) -> None:
    candidate_key = f"memory_shadow:{batch.batch_key}:{decision}"
    existing = list_data_point_extraction_debug(
        user_id=batch.user_id,
        source_id=batch.conversation_id,
        limit=100,
    )
    if any(row.get("candidate_key") == candidate_key for row in existing):
        return
    save_data_point_extraction_debug(
        {
            "user_id": batch.user_id,
            "source_kind": "agent_conversation",
            "source_id": batch.conversation_id,
            "import_id": None,
            "candidate_key": candidate_key,
            "decision": decision,
            "candidate": candidate,
            "review": review,
            "metadata": {
                "title": "Background memory shadow",
                "extractor": "memory_background_v2_shadow",
                "batch_key": batch.batch_key,
                "new_start_message_index": batch.new_start_message_index,
                "new_end_message_index": batch.new_end_message_index,
                "context_message_indexes": [
                    message.message_index for message in batch.context_messages
                ],
                "evidence_eligible_message_indexes": list(batch.evidence_message_indexes),
                "state_version": state_version,
                "live_writes": live_writes,
            },
        }
    )


def _operation_dict(operation: MemoryOperation) -> dict[str, Any]:
    return {
        "operation": operation.operation,
        "target_memory_id": operation.target_memory_id,
        "data_point_type": operation.data_point_type,
        "category": operation.category,
        "key": operation.key,
        "label": operation.label,
        "value": operation.value,
        "confidence": operation.confidence,
        "evidence_message_indexes": list(operation.evidence_message_indexes),
    }


def _result_decision(
    analysis: MemoryAnalysis,
    application_result: Any,
    thread_application_result: Any,
) -> str:
    if thread_application_result and thread_application_result.applied_count:
        return "live_applied"
    if not analysis.valid:
        return "shadow_invalid"
    if application_result is None:
        return "shadow_valid"
    if application_result.applied_count:
        return "live_applied"
    if application_result.deferred_count:
        return "live_deferred"
    return "shadow_valid"


def _handoff_dict(handoff: MemoryHandoff) -> dict[str, Any]:
    return {
        "summary": handoff.summary,
        "active_people": list(handoff.active_people),
        "active_topics": list(handoff.active_topics),
        "unresolved_references": list(handoff.unresolved_references),
    }


def _context_overlap() -> int:
    try:
        return max(0, int(os.getenv("MEMORY_BACKGROUND_V2_CONTEXT_OVERLAP", "12")))
    except ValueError:
        return DEFAULT_CONTEXT_OVERLAP


def _timeout_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("MEMORY_BACKGROUND_V2_TIMEOUT_SECONDS", "120")))
    except ValueError:
        return 120.0


def _lease_seconds() -> float:
    """Keep the claim beyond the bounded provider timeout without another flag."""
    return _timeout_seconds() + 30.0


__all__ = [
    "background_cognition_enabled",
    "background_cognition_threshold",
    "run_background_cognition",
    "should_schedule_background_cognition",
    "should_schedule_idle_background_cognition",
]
