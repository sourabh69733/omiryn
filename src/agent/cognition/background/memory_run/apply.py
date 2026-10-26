"""Saving what a memory run found besides memories and threads: the user card, Omi's self notes, open
questions and vibe lines. Ids derive from the batch, so a retried batch never adds anything twice."""

from __future__ import annotations

import logging
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from agent.cognition.background.vibe.verify import stored_quote_lookup, verify_vibe_updates
from agent.memory_engine.memories.focus import without_focus_lines
from agent.memory_engine.memories.open_questions import OpenQuestionChanges
from agent.memory_engine.memories.operations import MemoryRetractProposal, MemorySupersedeProposal
from agent.memory_engine.memories.self_notes import SelfNoteChanges
from agent.memory_engine.memories.user_card import without_replaced_lines
from agent.memory_engine.memories.vibe import with_current_proof
from agent.memory_engine.processing.models import MemoryBatch
from realtime import conversation_event, realtime_hub
from storage import list_agent_memories
from storage.open_questions import add_open_questions, resolve_open_questions
from storage.self_notes import add_self_notes, resolve_self_notes
from storage.user_cards import set_user_card
from storage.vibe_cards import update_vibe_card

logger = logging.getLogger(__name__)


def update_user_card(user_id: str, new_card: str | None, current_card: str | None, replaced_ids: dict[str, str | None]) -> None:
    """Writes the model's card (or the current one), without lines about a finished focus or a
    memory this batch replaced. The model sometimes updates a memory but returns no new card; its
    old line must not stay."""
    memories = list_agent_memories(user_id)
    focus = [memory for memory in memories if memory.get("focus") and memory.get("status") == "active"]
    replaced = [(memory, replaced_ids[memory["id"]]) for memory in memories if memory["id"] in replaced_ids]
    card = without_replaced_lines(without_focus_lines(new_card or current_card or "", focus), replaced)
    if card != current_card:
        set_user_card(user_id, card)


def replaced_memory_ids(operations: tuple[Any, ...]) -> dict[str, str | None]:
    """Memories this batch replaced or retracted, with the text of what replaced each."""
    replaced: dict[str, str | None] = {}
    for operation in operations:
        if isinstance(operation, MemorySupersedeProposal):
            new = operation.replacement
            replaced[operation.target_memory_id] = f"{new.statement or ''} {new.value}"
        elif isinstance(operation, MemoryRetractProposal):
            replaced[operation.target_memory_id] = None
    return replaced


def apply_self_notes(batch: MemoryBatch, changes: SelfNoteChanges) -> None:
    # IDs derive from the batch, so a retried batch cannot add the same note twice.
    add_self_notes(
        batch.user_id,
        batch.conversation_id,
        [
            {
                "id": str(uuid5(NAMESPACE_URL, f"self-note:{batch.batch_key}:{position}")),
                "kind": note.kind,
                "text": note.text,
                "message_index": note.message_index,
                "due_at": note.due_at,
            }
            for position, note in enumerate(changes.adds)
        ],
    )
    resolve_self_notes(batch.user_id, [(item.note_id, item.status) for item in changes.resolves])


def apply_open_questions(batch: MemoryBatch, changes: OpenQuestionChanges) -> None:
    # IDs derive from the batch, so a retried batch cannot add the same question twice.
    add_open_questions(
        batch.user_id,
        batch.conversation_id,
        [
            {
                "id": str(uuid5(NAMESPACE_URL, f"open-question:{batch.batch_key}:{position}")),
                "text": question.text,
                "message_index": question.message_index,
                "about_memory_ids": list(question.about_memory_ids),
            }
            for position, question in enumerate(changes.adds)
        ],
    )
    resolve_open_questions(
        batch.user_id, [(item.question_id, item.status) for item in changes.resolves]
    )


async def apply_vibe(
    batch: MemoryBatch,
    current: dict[str, Any],
    updates: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Saves only lines the proof check confirms; returns what was saved (or an error marker)."""
    conversation_id, user_id = batch.conversation_id, batch.user_id
    try:
        # A rewritten line is re-proven with its old and new proof; only what shows the new
        # text is kept, so proof for what the line used to say does not linger.
        verified = await verify_vibe_updates(
            with_current_proof(updates, current["areas"]),
            stored_quote_lookup(user_id),
            conversation_id=conversation_id,
        )
    except Exception as error:  # an unchecked line is never saved
        logger.warning("agent.vibe.verify_failed conversation_id=%s error_type=%s", conversation_id, type(error).__name__)
        return {"error": type(error).__name__}
    if not verified:
        return {}
    saved = update_vibe_card(user_id, verified, replace_evidence=True)
    verified = {area_id: verified[area_id] for area_id in saved.get("applied", verified)}
    if saved["milestone"] != current["milestone"]:
        # The open chat shows it; the companion hears about it on its next reply.
        await realtime_hub.publish(
            conversation_event(
                "vibe.milestone",
                conversation_id,
                payload={"milestone": saved["milestone"], "previous": current["milestone"]},
            )
        )
    return verified


__all__ = ["apply_open_questions", "apply_self_notes", "apply_vibe", "replaced_memory_ids", "update_user_card"]
