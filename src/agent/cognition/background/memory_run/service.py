"""The memory run on one chat: claim the next batch of new messages, ask the background model, check
what it proposes, save it, and record what happened.

Parts: settings (knobs), inputs (what the model reads), apply (card, self notes, open questions,
vibe), debug (the record of each run).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

from agent.cognition.background.memory_run.apply import (
    apply_open_questions,
    apply_self_notes,
    apply_vibe,
    replaced_memory_ids,
    update_user_card,
)
from agent.cognition.background.memory_run.coordination import interpret_background_cognition
from agent.cognition.background.memory_run.debug import handoff_dict, operation_dict, result_decision, save_cognition_debug_once
from agent.cognition.background.memory_run.inputs import existing_memory_context, open_question_context, self_note_context
from agent.cognition.background.memory_run.prompt import background_cognition_prompt
from agent.cognition.background.memory_run.settings import (
    MAX_BATCH_CONTENT_FAILURES,
    background_cognition_enabled,
    background_cognition_threshold,
    background_model,
    context_overlap,
    lease_seconds,
    timeout_seconds,
    user_lease_seconds,
)
from agent.config import agent_pipeline_config
from agent.context_engine.threads import apply_validated_thread_proposal, background_thread_candidates
from agent.memory_engine.memories.application import apply_validated_memory_analysis_v3
from agent.memory_engine.memories.embeddings import embed_memory_query, index_agent_memories, refresh_user_memory_embeddings
from agent.memory_engine.memories.vibe import rejected_texts, vibe_texts
from agent.memory_engine.processing.application import apply_validated_memory_analysis
from agent.memory_engine.processing.context import build_memory_batch
from agent.memory_engine.processing.models import MemoryBatch, MemoryProcessingState
from agent.memory_engine.processing.service import (
    claim_processing_batch,
    claim_user_lease,
    get_processing_state,
    release_processing_batch,
    release_user_lease,
    save_processing_state,
)
from agent.observability.usage import BACKGROUND_COGNITION, MEMORY_SHADOW_EXTRACT
from agent.providers import analyze_background_cognition
from storage import (
    attach_agent_usage_result,
    get_conversation,
    get_user_card,
    get_user_timezone,
    latest_agent_usage_event_id,
    record_memory_batch_failure,
)
from storage.conversations import is_temporary_conversation
from storage.vibe_cards import get_vibe_card

logger = logging.getLogger(__name__)


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
        context_overlap=context_overlap(),
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
    return bool(batch and batch.meaningful_user_message_count >= background_cognition_threshold())


def has_pending_background_cognition(
    conversation_id: str,
    user_id: str,
    messages: list[dict[str, object]],
) -> bool:
    """True when meaningful user messages are waiting for background cognition."""
    batch = _pending_background_cognition_batch(
        conversation_id,
        user_id,
        messages,
        state=get_processing_state(conversation_id, user_id),
    )
    return bool(batch and batch.meaningful_user_message_count > 0)


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
        batch and 0 < batch.meaningful_user_message_count < background_cognition_threshold()
    )


async def run_background_cognition(
    conversation_id: str,
    user_id: str,
    messages: list[dict[str, object]],
    model: str | None = None,
) -> dict[str, Any]:
    """Claim and analyze one batch without duplicating its model call."""
    if is_temporary_conversation(conversation_id, user_id):
        # Temporary Chat: nothing is learned from it.
        return {"status": "temporary_chat", "operation_count": 0}
    state = get_processing_state(conversation_id, user_id)
    batch = _pending_background_cognition_batch(
        conversation_id,
        user_id,
        messages,
        state=state,
    )
    if batch is None or batch.meaningful_user_message_count == 0:
        return {"status": "no_pending_messages", "operation_count": 0}

    # One chat at a time per user: each run reads the cards and memories the last one wrote.
    user_lease = claim_user_lease(user_id, conversation_id, lease_seconds=user_lease_seconds())
    if user_lease is None:
        return {
            "status": "already_processing",
            "batch_key": batch.batch_key,
            "operation_count": 0,
        }
    try:
        lease_owner = claim_processing_batch(
            conversation_id,
            user_id,
            batch.batch_key,
            expected_processed_index=(
                state.processed_through_message_index if state is not None else -1
            ),
            lease_seconds=lease_seconds(),
        )
        if lease_owner is None:
            return {
                "status": "already_processing",
                "batch_key": batch.batch_key,
                "operation_count": 0,
            }
        return await _run_with_batch_lease(batch, state, model, lease_owner)
    finally:
        release_user_lease(user_id, user_lease)


async def _run_with_batch_lease(
    batch: MemoryBatch,
    state: MemoryProcessingState | None,
    model: str | None,
    lease_owner: str,
) -> dict[str, Any]:
    conversation_id, user_id = batch.conversation_id, batch.user_id

    memory_version = agent_pipeline_config().memory_contract_version
    request_kind = BACKGROUND_COGNITION if memory_version == 3 else MEMORY_SHADOW_EXTRACT
    previous_usage_event_id = latest_agent_usage_event_id(
        conversation_id, user_id, request_kind
    )
    try:
        result = await _run_claimed_background_cognition(
            batch=batch,
            state=state,
            model=model,
        )
        if result.get("status") in {"live_error", "shadow_error"} and get_conversation(
            conversation_id, user_id
        ) is None:
            # The chat was deleted while this batch waited; nothing to do.
            result = {"status": "conversation_unavailable", "batch_key": batch.batch_key, "operation_count": 0}
        elif result.pop("content_failure", False):
            result = _count_failure_or_skip(batch, result)
        attach_agent_usage_result(
            conversation_id,
            user_id,
            request_kind,
            _usage_result_summary(result),
            previous_event_id=previous_usage_event_id,
        )
        return result
    finally:
        release_processing_batch(batch.batch_key, user_id, lease_owner)


def _usage_result_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Keep the usage-facing cognition result small and non-sensitive."""
    return {
        "status": str(result.get("status") or "unknown"),
        "memory_operations": int(result.get("operation_count") or 0),
        "memories_applied": int(result.get("applied_count") or 0),
        "memories_deferred": int(result.get("deferred_count") or 0),
        "thread_operations_applied": int(result.get("thread_applied_count") or 0),
    }


@dataclass(frozen=True)
class _Inputs:
    """What the model reads besides the new messages (v3 parts are None before v3)."""

    existing_memories: list[dict[str, Any]]
    thread_candidates: list[dict[str, Any]]
    user_card: str | None
    self_notes: list[dict[str, Any]] | None
    open_questions: list[dict[str, Any]] | None
    vibe_card: dict[str, Any] | None


async def _read_inputs(batch: MemoryBatch, memory_version: int) -> _Inputs:
    user_id = batch.user_id
    evidence_text = " ".join(message.content for message in batch.new_messages if message.role == "user")
    v3 = memory_version == 3
    query_embedding = await embed_memory_query(evidence_text, conversation_id=batch.conversation_id) if v3 else None
    return _Inputs(
        existing_memories=existing_memory_context(user_id, memory_version, evidence_text, query_embedding=query_embedding),
        thread_candidates=background_thread_candidates(batch.conversation_id, user_id, evidence_text),
        user_card=(get_user_card(user_id) or "") if v3 else None,
        self_notes=self_note_context(user_id) if v3 else None,
        open_questions=open_question_context(user_id) if v3 else None,
        vibe_card=get_vibe_card(user_id) if v3 else None,
    )


async def _run_claimed_background_cognition(
    *,
    batch: MemoryBatch,
    state: MemoryProcessingState | None,
    model: str | None,
) -> dict[str, Any]:
    """Run the expensive work after this worker owns the batch lease: read, ask, check, save."""
    config = agent_pipeline_config()
    memory_version = config.memory_contract_version
    writes_memories = config.live_memory_writes or config.live_v3_memory_writes
    inputs = await _read_inputs(batch, memory_version)
    application_result = None
    thread_application_result = None
    # Errors before the model answers (timeouts, outages) are retried forever; errors after it
    # come from the content and count toward skipping the batch.
    model_answered = False
    try:
        vibe_card = inputs.vibe_card
        raw = await analyze_background_cognition(
            background_cognition_prompt(
                batch,
                inputs.existing_memories,
                inputs.thread_candidates,
                get_user_timezone(batch.user_id),
                inputs.user_card,
                inputs.self_notes,
                vibe_texts(vibe_card["areas"]) if vibe_card is not None else None,
                rejected_texts(vibe_card.get("rejected")) if vibe_card is not None else None,
                inputs.open_questions,
            ),
            conversation_id=batch.conversation_id,
            model=background_model(model),
            timeout_seconds=timeout_seconds(),
            memory_version=memory_version,
        )
        model_answered = True
        cognition = interpret_background_cognition(
            raw,
            batch=batch,
            existing_memory_ids={str(memory["id"]) for memory in inputs.existing_memories if memory.get("targetable") is not False},
            thread_candidates=inputs.thread_candidates,
            memory_version=memory_version,
            active_self_note_ids={str(note["id"]) for note in inputs.self_notes or []},
            open_question_ids={str(question["id"]) for question in inputs.open_questions or []},
        )
        analysis = cognition.memory
        if memory_version == 3 and not analysis.valid:
            return _invalid_result(batch, state, analysis, raw, memory_version)

        # 1. Memories.
        if analysis.valid and writes_memories:
            try:
                application_result = await _apply_memories(batch, analysis, model, memory_version)
            except Exception as error:
                return _apply_error_result(batch, state, analysis, cognition, raw, memory_version, error)
        # 2. Threads.
        if bool(cognition.thread.get("valid")) and config.live_thread_writes:
            thread_application_result = apply_validated_thread_proposal(
                batch_key=batch.batch_key,
                conversation_id=batch.conversation_id,
                user_id=batch.user_id,
                message_index=batch.new_end_message_index,
                proposal=cognition.thread.get("proposal"),
            )
        # 3. Card, self notes, open questions, vibe.
        vibe_verified = await _apply_extras(batch, analysis, cognition, inputs, memory_version) if analysis.valid and writes_memories else None
        # 4. Move the cursor and keep a record.
        return _finish(batch, state, analysis, cognition, raw, memory_version, application_result, thread_application_result, vibe_verified)
    except Exception as error:
        live_attempted = config.live_memory_writes or config.live_v3_memory_writes or config.live_thread_writes
        live_writes = application_result is not None or thread_application_result is not None
        decision = "live_error" if live_attempted else "shadow_error"
        save_cognition_debug_once(
            batch=batch,
            memory_version=memory_version,
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
            "content_failure": model_answered and memory_version == 3,
        }


async def _apply_memories(batch: MemoryBatch, analysis: Any, model: str | None, memory_version: int) -> Any:
    if memory_version != 3:
        return apply_validated_memory_analysis(batch, analysis)
    result = apply_validated_memory_analysis_v3(batch, analysis, extractor_model=background_model(model))
    await index_agent_memories(result.memories, conversation_id=batch.conversation_id)
    # Heals memories whose embedding failed in an earlier run.
    await refresh_user_memory_embeddings(batch.user_id, conversation_id=batch.conversation_id)
    return result


async def _apply_extras(batch: MemoryBatch, analysis: Any, cognition: Any, inputs: _Inputs, memory_version: int) -> dict[str, Any] | None:
    """Card, self notes, open questions and vibe lines; returns the vibe lines that passed the proof check."""
    replaced_ids = replaced_memory_ids(analysis.operations) if memory_version == 3 else {}
    if cognition.user_card or replaced_ids:
        update_user_card(batch.user_id, cognition.user_card, inputs.user_card, replaced_ids)
    if not cognition.self_notes.empty:
        apply_self_notes(batch, cognition.self_notes)
    if not cognition.open_questions.empty:
        apply_open_questions(batch, cognition.open_questions)
    if cognition.vibe and inputs.vibe_card is not None:
        return await apply_vibe(batch, inputs.vibe_card, cognition.vibe)
    return None


def _invalid_result(batch: MemoryBatch, state: MemoryProcessingState | None, analysis: Any, raw: dict[str, Any], memory_version: int) -> dict[str, Any]:
    save_cognition_debug_once(
        batch=batch,
        memory_version=memory_version,
        decision="live_invalid",
        candidate={
            "model_decision": analysis.decision,
            "operations": [],
            "thread_operation": raw.get("thread_operation"),
        },
        review={
            "valid": False,
            "errors": list(analysis.errors),
            "live_writes": False,
        },
        state_version=state.version if state else 0,
    )
    return {
        "status": "live_invalid",
        "batch_key": batch.batch_key,
        "operation_count": 0,
        "errors": list(analysis.errors),
        "content_failure": True,
    }


def _apply_error_result(
    batch: MemoryBatch,
    state: MemoryProcessingState | None,
    analysis: Any,
    cognition: Any,
    raw: dict[str, Any],
    memory_version: int,
    error: Exception,
) -> dict[str, Any]:
    save_cognition_debug_once(
        batch=batch,
        memory_version=memory_version,
        decision="live_error",
        candidate={
            "model_decision": analysis.decision,
            "operations": [operation_dict(operation) for operation in analysis.operations],
            "thread_operation": raw.get("thread_operation"),
            "handoff": handoff_dict(analysis.handoff),
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
        "content_failure": True,
    }


def _finish(
    batch: MemoryBatch,
    state: MemoryProcessingState | None,
    analysis: Any,
    cognition: Any,
    raw: dict[str, Any],
    memory_version: int,
    application_result: Any,
    thread_application_result: Any,
    vibe_verified: dict[str, Any] | None,
) -> dict[str, Any]:
    """Moves the cursor past the batch, saves the handoff and the debug record, returns the result."""
    next_handoff = analysis.handoff if analysis.valid else batch.previous_handoff
    current_state = state or MemoryProcessingState(conversation_id=batch.conversation_id, user_id=batch.user_id)
    saved_state = save_processing_state(
        replace(
            current_state,
            processed_through_message_index=batch.new_end_message_index,
            last_batch_key=batch.batch_key,
            handoff=next_handoff,
        )
    )
    decision = result_decision(analysis, application_result, thread_application_result, memory_version=memory_version)
    live_writes = application_result is not None or thread_application_result is not None
    applied = application_result.applied_count if application_result else 0
    deferred = application_result.deferred_count if application_result else 0
    idempotent = application_result.idempotent if application_result else False
    thread_applied = thread_application_result.applied_count if thread_application_result else 0
    thread_idempotent = thread_application_result.idempotent if thread_application_result else False
    save_cognition_debug_once(
        batch=batch,
        memory_version=memory_version,
        decision=decision,
        candidate={
            "model_decision": analysis.decision,
            "operations": [operation_dict(operation) for operation in analysis.operations],
            "thread_operation": raw.get("thread_operation"),
            "handoff": handoff_dict(analysis.handoff),
            # Raw, so a missing card or note shows whether the model wrote it at all.
            "user_card": raw.get("user_card"),
            "vibe": raw.get("vibe"),
            # After the proof check; None when nothing was checked.
            "vibe_verified": vibe_verified,
            "self_notes": raw.get("self_notes"),
            "open_questions": raw.get("open_questions"),
        },
        review={
            "valid": analysis.valid,
            "errors": list(analysis.errors),
            # Parts the model got wrong that were dropped; the rest of the batch was saved.
            "dropped": list(getattr(analysis, "dropped", ())),
            "combined_valid": cognition.valid,
            "combined_errors": list(cognition.errors),
            "thread_valid": bool(cognition.thread.get("valid")),
            "thread_errors": list(cognition.thread.get("errors") or []),
            "thread_proposal": cognition.thread.get("proposal"),
            "live_writes": live_writes,
            "applied_count": applied,
            "deferred_count": deferred,
            "idempotent": idempotent,
            "thread_applied_count": thread_applied,
            "thread_idempotent": thread_idempotent,
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
        "applied_count": applied,
        "deferred_count": deferred,
        "idempotent": idempotent,
        "thread_applied_count": thread_applied,
        "thread_idempotent": thread_idempotent,
        "errors": list(analysis.errors),
        "processed_through_message_index": saved_state.processed_through_message_index,
    }


def _count_failure_or_skip(batch: MemoryBatch, result: dict[str, Any]) -> dict[str, Any]:
    """Count a content failure; after a few on the same batch, move the cursor past it.

    The model runs at temperature 0, so a batch that fails on its content fails the same way on
    every retry and would stop the conversation's memory for good.
    """
    error = "; ".join(result.get("errors") or [str(result.get("status"))])
    attempts = record_memory_batch_failure(
        batch.batch_key, batch.conversation_id, batch.user_id, error
    )
    if attempts < MAX_BATCH_CONTENT_FAILURES:
        return {**result, "failed_attempts": attempts}
    current = get_processing_state(batch.conversation_id, batch.user_id) or MemoryProcessingState(
        conversation_id=batch.conversation_id,
        user_id=batch.user_id,
    )
    # The previous summary and session log are kept; only this batch's messages are passed over.
    saved = save_processing_state(
        replace(
            current,
            processed_through_message_index=batch.new_end_message_index,
            last_batch_key=batch.batch_key,
        )
    )
    save_cognition_debug_once(
        batch=batch,
        memory_version=3,
        decision="skipped_after_failures",
        candidate={},
        review={"valid": False, "errors": [error[:300]], "attempts": attempts, "live_writes": False},
        state_version=saved.version,
    )
    logger.warning(
        "agent.memory_batch_skipped conversation_id=%s batch_key=%s attempts=%s",
        batch.conversation_id,
        batch.batch_key,
        attempts,
    )
    return {
        "status": "skipped_after_failures",
        "batch_key": batch.batch_key,
        "operation_count": 0,
        "errors": result.get("errors") or [],
        "processed_through_message_index": saved.processed_through_message_index,
    }


__all__ = [
    "MAX_BATCH_CONTENT_FAILURES",
    "background_cognition_enabled",
    "background_cognition_threshold",
    "has_pending_background_cognition",
    "run_background_cognition",
    "should_schedule_background_cognition",
    "should_schedule_idle_background_cognition",
]
