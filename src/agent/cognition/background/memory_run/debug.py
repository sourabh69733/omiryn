"""The debug record of each memory run (what the model proposed, what was checked and saved) and the
decision label it ends with. One record per batch and decision."""

from __future__ import annotations

from typing import Any

from agent.memory_engine.memories.operations import (
    MemoryAddProposal,
    MemoryProposalV3,
    MemoryReinforceProposal,
    MemoryRetractProposal,
    MemorySupersedeProposal,
)
from agent.memory_engine.processing.models import MemoryBatch, MemoryHandoff, MemoryOperation
from agent.memory_engine.processing.validation import MemoryAnalysis
from storage import list_data_point_extraction_debug
from storage.profile_facts import save_data_point_extraction_debug


def save_cognition_debug_once(
    *,
    batch: MemoryBatch,
    memory_version: int,
    decision: str,
    candidate: dict[str, Any],
    review: dict[str, Any],
    state_version: int,
    live_writes: bool = False,
) -> None:
    candidate_key = f"background_cognition:{batch.batch_key}:{decision}"
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
                "title": "Background cognition",
                "extractor": f"background_cognition_v{memory_version}",
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


def operation_dict(operation: MemoryOperation | MemoryProposalV3) -> dict[str, Any]:
    if isinstance(operation, MemoryAddProposal):
        return _add_operation_dict(operation, "add")
    if isinstance(operation, MemoryReinforceProposal):
        return {
            "operation": "reinforce",
            "target_memory_id": operation.target_memory_id,
            "confidence": operation.confidence,
            "importance": operation.importance,
            "evidence_message_indexes": list(operation.evidence_message_indexes),
        }
    if isinstance(operation, MemorySupersedeProposal):
        return {
            **_add_operation_dict(operation.replacement, "supersede"),
            "target_memory_id": operation.target_memory_id,
        }
    if isinstance(operation, MemoryRetractProposal):
        return {
            "operation": "retract",
            "target_memory_id": operation.target_memory_id,
            "evidence_message_indexes": list(operation.evidence_message_indexes),
        }
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


def _add_operation_dict(operation: MemoryAddProposal, name: str) -> dict[str, Any]:
    return {
        "operation": name,
        "memory_kind": operation.kind.value,
        "purposes": sorted(purpose.value for purpose in operation.purposes),
        "key": operation.key,
        "value": operation.value,
        "sensitivity": operation.sensitivity.value,
        "confidence": operation.confidence,
        "importance": operation.importance,
        "focus": operation.focus,
        "evidence_message_indexes": list(operation.evidence_message_indexes),
    }


def result_decision(
    analysis: MemoryAnalysis,
    application_result: Any,
    thread_application_result: Any,
    *,
    memory_version: int,
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
    return "no_change" if memory_version == 3 else "shadow_valid"


def handoff_dict(handoff: MemoryHandoff) -> dict[str, Any]:
    return {
        "summary": handoff.summary,
        "active_people": list(handoff.active_people),
        "active_topics": list(handoff.active_topics),
        "unresolved_references": list(handoff.unresolved_references),
        "conversation_summary": handoff.conversation_summary,
        "session_log": [
            {"started_at": e.started_at, "gist": e.gist, "unfinished": e.unfinished}
            for e in handoff.session_log
        ],
    }


__all__ = ["handoff_dict", "operation_dict", "result_decision", "save_cognition_debug_once"]
