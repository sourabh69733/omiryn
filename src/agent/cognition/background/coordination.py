"""Splits one background response across memory and thread domain contracts."""

from __future__ import annotations

from typing import Any

from agent.context_engine.conversation_engine.state import evaluate_thread_operation_shadow
from agent.memory_engine.processing.models import MemoryBatch
from agent.memory_engine.memories.open_questions import OpenQuestionChanges, validate_open_questions
from agent.memory_engine.memories.self_notes import SelfNoteChanges, validate_self_notes
from agent.memory_engine.memories.user_card import validate_user_card
from agent.memory_engine.memories.vibe import validate_vibe_updates
from agent.memory_engine.memories.validation import validate_memory_analysis_v3
from agent.memory_engine.processing.validation import validate_memory_analysis
from agent.shared.utils import unknown_fields

from .models import BackgroundCognitionAnalysis


def interpret_background_cognition(
    raw: Any,
    *,
    batch: MemoryBatch,
    existing_memory_ids: set[str],
    thread_candidates: list[dict[str, object]],
    memory_version: int = 2,
    active_self_note_ids: set[str] | None = None,
    open_question_ids: set[str] | None = None,
) -> BackgroundCognitionAnalysis:
    """Delegate each portion of one model response to its owning domain."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        raw = {}
        errors.append("background cognition analysis must be an object")
    unsupported = unknown_fields(
        raw,
        {
            "decision",
            "operations",
            "thread_operation",
            "handoff",
            "user_card",
            "vibe",
            "self_notes",
            "open_questions",
        },
    )
    if unsupported:
        errors.append(f"unsupported top-level fields: {', '.join(unsupported)}")

    decision = raw.get("decision")
    operations = raw.get("operations")
    thread_operation = raw.get("thread_operation")
    operation_name = (
        str(thread_operation.get("operation")) if isinstance(thread_operation, dict) else "invalid"
    )
    if decision not in {"propose", "no_change"}:
        errors.append("decision must be propose or no_change")
    has_memory_change = isinstance(operations, list) and bool(operations)
    has_thread_change = operation_name not in {"none", "invalid"}
    if decision == "no_change" and (has_memory_change or has_thread_change):
        errors.append("no_change cannot include memory or thread operations")
    if decision == "propose" and not (has_memory_change or has_thread_change):
        errors.append("propose requires a memory or thread operation")

    memory_payload = {
        "decision": "propose" if has_memory_change else "no_change",
        "operations": operations if isinstance(operations, list) else operations,
        "handoff": raw.get("handoff"),
    }
    memory = (
        validate_memory_analysis_v3(
            memory_payload,
            batch=batch,
            existing_memory_ids=existing_memory_ids,
        )
        if memory_version == 3
        else validate_memory_analysis(
            memory_payload,
            batch=batch,
            existing_memory_ids=existing_memory_ids,
        )
    )
    candidate_ids = {
        str(candidate["id"])
        for candidate in thread_candidates
        if isinstance(candidate, dict) and candidate.get("id")
    }
    thread = evaluate_thread_operation_shadow(
        thread_operation,
        conversation_id=batch.conversation_id,
        user_id=batch.user_id,
        message_index=batch.new_end_message_index,
        candidate_thread_ids=candidate_ids,
        message_roles={
            message.message_index: message.role
            for message in batch.messages
            if message.content.strip()
        },
    )
    errors.extend(f"memory: {error}" for error in memory.errors)
    errors.extend(f"thread: {error}" for error in thread.get("errors") or [])
    return BackgroundCognitionAnalysis(
        decision=str(decision or "invalid"),
        memory=memory,
        thread=thread,
        thread_operation=operation_name,
        valid=not errors and memory.valid and bool(thread.get("valid")),
        errors=tuple(errors),
        user_card=validate_user_card(raw.get("user_card")) if memory_version == 3 else None,
        vibe=(
            validate_vibe_updates(raw.get("vibe"), resolve_evidence=_user_message_resolver(batch))
            if memory_version == 3
            else {}
        ),
        self_notes=(
            validate_self_notes(
                raw.get("self_notes"),
                batch=batch,
                active_note_ids=active_self_note_ids or set(),
            )
            if memory_version == 3
            else SelfNoteChanges()
        ),
        open_questions=(
            validate_open_questions(
                raw.get("open_questions"),
                batch=batch,
                open_question_ids=open_question_ids or set(),
                memory_ids=existing_memory_ids,
            )
            if memory_version == 3
            else OpenQuestionChanges()
        ),
    )


def _user_message_resolver(batch: MemoryBatch):
    """Vibe evidence must be a user message the model saw in this batch."""
    user_messages = {
        message.message_index: message
        for message in batch.messages
        if message.role == "user" and message.content.strip()
    }

    def resolve(ref: Any) -> dict[str, Any] | None:
        if isinstance(ref, bool) or not isinstance(ref, int) or ref not in user_messages:
            return None
        sent_at = user_messages[ref].sent_at
        return {
            "conversation_id": batch.conversation_id,
            "message_index": ref,
            **({"sent_at": sent_at} if sent_at else {}),
        }

    return resolve


__all__ = ["interpret_background_cognition"]
