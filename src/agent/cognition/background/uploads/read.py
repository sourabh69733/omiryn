"""Reads an uploaded chat, both sides, into memories about the user and a digest of the chat.

Parts of the chat (about 30 user lines each, with the other person's lines between them) are read
at the same time by a fast model with the upload prompt: topics, facts about the user, facts about
the other person, plans, how the two talk. One merge call by the background model joins them into
a digest (summary, index line, topics with dates and lines, a card for the other person) and picks
which memories to keep. Memories are saved in one batch over the whole hidden chat after every part
is read, so a retry starts clean; the digest is stored with the upload and deleted with it.

Progress is kept in the upload's metadata ("reading"), so the app can show it after a reload.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
from dataclasses import replace
from time import monotonic
from typing import Any

from agent.memory_engine.memories.application import apply_validated_memory_analysis_v3
from agent.memory_engine.memories.embeddings import index_agent_memories
from agent.memory_engine.memories.focus import without_focus_lines
from agent.memory_engine.memories.operations import MemoryAddProposal, MemoryAnalysisV3
from agent.memory_engine.memories.user_card import validate_user_card, without_replaced_lines
from agent.memory_engine.memories.vibe import vibe_texts
from agent.memory_engine.processing.context import build_memory_batch
from agent.memory_engine.processing.models import MemoryBatch, MemoryHandoff, MemoryProcessingState
from agent.memory_engine.processing.service import (
    claim_user_lease,
    get_processing_state,
    release_user_lease,
    save_processing_state,
)
from agent.providers import analyze_upload_merge, analyze_upload_part
from agent.shared.clock import utc_now_iso
from agent.shared.timeline import user_zone
from storage import get_user_card, get_user_timezone, list_agent_memories
from storage.context_sources import get_context_source_metadata, update_context_source_metadata
from storage.upload_digests import save_upload_digest
from storage.user_cards import set_user_card
from storage.vibe_cards import get_vibe_card

from agent.cognition.background.uploads.person_card import build_person_card
from agent.cognition.background.memory_run.apply import apply_vibe, replaced_memory_ids
from agent.cognition.background.memory_run.inputs import existing_memory_context
from agent.cognition.background.memory_run.settings import context_overlap, timeout_seconds
from agent.cognition.background.uploads.notes import (
    Gathered,
    PartNotes,
    build_digest,
    chat_dates,
    check_part,
    gather,
    merge_input,
    merged_memories,
    part_input,
    relationship_memory,
)

logger = logging.getLogger(__name__)

# User lines per part; a bigger upload gets bigger parts so at most MAX_PARTS run at once. Output
# speed is the limit, so smaller parts finish sooner.
PART_USER_LINES = int(os.getenv("MEMORY_UPLOAD_PART_LINES", "30"))
MAX_PARTS = int(os.getenv("MEMORY_UPLOAD_MAX_PARTS", "6"))
# The whole upload is stored and searchable; memories and the digest come from the user's newest
# lines only, so reading stays about a minute however long the chat is.
READ_USER_LINES = int(os.getenv("MEMORY_UPLOAD_READ_LINES", "300"))
_EVERY_LINE = 10**9
# On a 150-line upload (2026-10-21): Qwen3-Next 80B read parts in ~25 s; Qwen3 235B took ~170 s.
DEFAULT_UPLOAD_MODEL = "Qwen/Qwen3-Next-80B-A3B-Instruct"
# Waits before each retry. The provider answers "model busy" (429) under load, so an instant retry
# fails too; the last try uses the other model.
RETRY_WAITS = (5.0, 15.0)


async def read_upload(conversation: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Learn from a whole uploaded chat; raises on failure so the job retries from the start."""
    conversation_id = str(conversation["id"])
    source_id = str(conversation.get("import_source_id") or "")
    messages = list(conversation.get("messages") or [])
    lease = claim_user_lease(user_id, conversation_id, lease_seconds=timeout_seconds() * 2 + 60)
    if lease is None:
        return {"status": "already_processing", "operation_count": 0}
    started = monotonic()
    try:
        parts = upload_parts(conversation_id, user_id, messages)
        whole = build_memory_batch(
            conversation_id=conversation_id,
            user_id=user_id,
            messages=messages,
            context_overlap=0,
            max_meaningful_user_messages=_EVERY_LINE,
        )
        if whole is None or not parts:
            _progress(source_id, user_id, state="done", parts=0, parts_done=0, learned=0, topics=0)
            return {"status": "no_pending_messages", "operation_count": 0}
        _progress(source_id, user_id, state="reading", parts=len(parts), parts_done=0, learned=0, started_at=utc_now_iso(), step_started_at=utc_now_iso())
        partner = chat_partner(whole)
        context = _shared_context(user_id, whole)
        zone = user_zone(context["timezone"])
        done = 0

        async def read(part: MemoryBatch) -> PartNotes:
            nonlocal done
            notes = await _read_part(part, partner, zone)
            done += 1
            _progress(source_id, user_id, parts_done=done)
            return notes

        gathered = gather(list(await asyncio.gather(*(read(part) for part in parts))))
        _progress(source_id, user_id, state="merging", step_started_at=utc_now_iso())
        merge = await _merge(conversation_id, gathered, partner, whole, context)
        operations = merged_memories(gathered, merge, context["memories"])
        operations += relationship_memory(partner, merge, gathered, whole, context["memories"])
        applied = None
        if operations:
            applied = apply_validated_memory_analysis_v3(
                whole,
                MemoryAnalysisV3(decision="propose", operations=operations, handoff=MemoryHandoff(), valid=True),
                extractor_model=upload_model(),
            )
        # Saved before the rest, so a retry never applies the memories twice.
        state = get_processing_state(conversation_id, user_id) or MemoryProcessingState(conversation_id=conversation_id, user_id=user_id)
        save_processing_state(replace(state, processed_through_message_index=whole.new_end_message_index, last_batch_key=whole.batch_key))
        digest = build_digest(partner, merge, gathered, whole)
        if partner:
            # Facts about them from the whole chat, each with its real line (not only the newest part).
            digest["person_card"] = await build_person_card(messages, partner, zone, conversation_id=conversation_id, model=upload_model())
        if source_id:
            save_upload_digest(source_id, user_id, conversation_id, partner, {**digest, "read_at": utc_now_iso()})
        await _save_after(whole, applied, operations, merge, gathered, context)
        learned = applied.applied_count if applied else 0
        seconds = round(monotonic() - started, 1)
        # Done once the chat is searchable too (the job indexes it next and marks it done).
        _progress(source_id, user_id, state="indexing", learned=learned, topics=len(digest["threads"]), seconds=seconds, step_started_at=utc_now_iso())
        logger.info("agent.upload_read conversation_id=%s parts=%s learned=%s topics=%s seconds=%s", conversation_id, len(parts), learned, len(digest["threads"]), seconds)
        return {"status": "upload_read", "parts": len(parts), "applied_count": learned, "topics": len(digest["threads"]), "seconds": seconds, "operation_count": len(operations)}
    except Exception:
        _progress(source_id, user_id, state="failed")
        raise
    finally:
        release_user_lease(user_id, lease)


def upload_model() -> str | None:
    """MEMORY_UPLOAD_MODEL, else a fast default on DeepInfra, else the background model."""
    configured = os.getenv("MEMORY_UPLOAD_MODEL", "").strip()
    if configured:
        return configured
    if os.getenv("AGENT_PROVIDER", "").strip().lower() == "deepinfra":
        return DEFAULT_UPLOAD_MODEL
    return _background_model()


def merge_model() -> str | None:
    """MEMORY_UPLOAD_MERGE_MODEL, else the upload model. The merge writes ~3K tokens; Qwen3 235B
    timed out on it twice at ~10 tokens a second (2026-10-22), Qwen3-Next wrote it in 46 s."""
    return os.getenv("MEMORY_UPLOAD_MERGE_MODEL", "").strip() or upload_model()


def _background_model() -> str | None:
    return os.getenv("MEMORY_BACKGROUND_V2_MODEL", "").strip() or None


def upload_parts(conversation_id: str, user_id: str, messages: list[dict[str, Any]]) -> list[MemoryBatch]:
    """The newest READ_USER_LINES user lines split into parts of about PART_USER_LINES, at most MAX_PARTS."""
    user_positions = [index for index, message in enumerate(messages) if message.get("role") == "user"]
    read = user_positions[-READ_USER_LINES:]
    per_part = max(PART_USER_LINES, math.ceil(len(read) / MAX_PARTS))
    parts: list[MemoryBatch] = []
    cursor = read[0] - 1 if read else -1
    while True:
        batch = build_memory_batch(
            conversation_id=conversation_id,
            user_id=user_id,
            messages=messages,
            state=MemoryProcessingState(conversation_id=conversation_id, user_id=user_id, processed_through_message_index=cursor),
            context_overlap=context_overlap(),
            max_meaningful_user_messages=per_part,
        )
        if batch is None:
            return parts
        if batch.meaningful_user_message_count:
            parts.append(batch)
        cursor = batch.new_end_message_index


def chat_partner(whole: MemoryBatch) -> str | None:
    """Who the user was chatting with: the other person with the most lines, None for notes."""
    counts: dict[str, int] = {}
    for message in whole.messages:
        if message.role == "other" and message.speaker:
            counts[message.speaker] = counts.get(message.speaker, 0) + 1
    return max(counts, key=counts.__getitem__) if counts else None


def _attempt_models(first: str | None, other: str | None) -> list[str | None]:
    return [first] * len(RETRY_WAITS) + [other or first]


async def _read_part(part: MemoryBatch, partner: str | None, zone: Any) -> PartNotes:
    """One part through the upload prompt. A failed call is retried after a wait; a part that comes
    back empty is read once more by the other model, since the fast one sometimes skips a part."""
    text = json.dumps(part_input(part, partner, zone), ensure_ascii=False)
    models = _attempt_models(upload_model(), _background_model())
    error: Exception | None = None
    attempt = 0
    while attempt < len(models):
        if attempt and error is not None:
            await asyncio.sleep(RETRY_WAITS[min(attempt, len(RETRY_WAITS)) - 1])
        try:
            notes = check_part(await analyze_upload_part(text, conversation_id=part.conversation_id, model=models[attempt]), part)
        except Exception as caught:  # provider or parse failure
            error = caught
            logger.warning("agent.upload_read.part_failed attempt=%s error_type=%s", attempt + 1, type(caught).__name__)
            attempt += 1
            continue
        if notes.empty and models[attempt] != models[-1]:
            error, attempt = None, len(models) - 1
            continue
        return notes
    raise error or RuntimeError("upload part was not read")


async def _merge(conversation_id: str, gathered: Gathered, partner: str | None, whole: MemoryBatch, context: dict[str, Any]) -> dict[str, Any]:
    """One merge call; the background model if the merge model stays busy."""
    if not (gathered.candidates or gathered.threads or gathered.about_other or gathered.plans):
        return {}
    text = json.dumps(
        merge_input(
            gathered,
            partner=partner,
            dates=chat_dates(whole),
            card=context["card"],
            memories=context["memories"],
            vibe=vibe_texts(context["vibe"]["areas"]) if context["vibe"] else {},
        ),
        ensure_ascii=False,
    )
    models = _attempt_models(merge_model(), _background_model())
    for attempt, model in enumerate(models):
        if attempt:
            await asyncio.sleep(RETRY_WAITS[min(attempt, len(RETRY_WAITS)) - 1])
        try:
            raw = await analyze_upload_merge(text, conversation_id=conversation_id, model=model)
            return raw if isinstance(raw, dict) else {}
        except Exception as error:
            if attempt == len(models) - 1:
                raise
            logger.warning("agent.upload_read.merge_failed attempt=%s error_type=%s", attempt + 1, type(error).__name__)
    return {}


async def _save_after(whole: MemoryBatch, applied: Any, operations: tuple[Any, ...], merge: dict[str, Any], gathered: Gathered, context: dict[str, Any]) -> None:
    """Embeddings, card and vibe; each is best effort, the memories are already saved."""
    user_id = whole.user_id
    if applied is not None:
        try:
            await index_agent_memories(applied.memories, conversation_id=whole.conversation_id)
        except Exception as error:
            logger.warning("agent.upload_read.index_failed error_type=%s", type(error).__name__)
    card = validate_user_card(card_lines(merge.get("user_card")))
    replaced_ids = replaced_memory_ids(operations)
    if card or replaced_ids:
        memories = list_agent_memories(user_id)
        focus = [memory for memory in memories if memory.get("focus") and memory.get("status") == "active"]
        replaced = [(memory, replaced_ids[memory["id"]]) for memory in memories if memory["id"] in replaced_ids]
        new_card = without_replaced_lines(without_focus_lines(card or context["card"], focus), replaced)
        if new_card != context["card"]:
            set_user_card(user_id, new_card)
    updates = merge_vibe(merge.get("vibe"), gathered.vibe, memory_proof(whole, gathered.candidates))
    if updates and context["vibe"] is not None:
        await apply_vibe(whole, context["vibe"], updates)


def card_lines(card: Any) -> Any:
    """One fact per line: a card written as a list or as one paragraph becomes lines."""
    if isinstance(card, list):
        return "\n".join(str(line).strip() for line in card if isinstance(line, str) and line.strip()) or None
    if not isinstance(card, str) or "\n" in card.strip():
        return card
    return "\n".join(part.strip() for part in re.split(r"(?<=[.!?])\s+", card.strip()) if part.strip())


def memory_proof(whole: MemoryBatch, candidates: list[tuple[str, MemoryAddProposal]]) -> dict[str, list[dict[str, Any]]]:
    """The user messages behind each memory candidate, in the form vibe proof takes."""
    sent = {message.message_index: message.sent_at for message in whole.messages}
    return {
        candidate_id: [
            {"conversation_id": whole.conversation_id, "message_index": index, **({"sent_at": sent[index]} if sent.get(index) else {})}
            for index in proposal.evidence_message_indexes
        ]
        for candidate_id, proposal in candidates
    }


def merge_vibe(
    chosen: Any,
    vibe_candidates: dict[str, list[dict[str, Any]]],
    memory_proof: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, dict[str, Any]]:
    """One line per area with the proof of the lines and memories it came from.

    A line without proof is never kept (the proof check would drop it anyway). When the merge
    skipped an area that has candidate lines, the line with the most proof stands.
    """
    chosen = chosen if isinstance(chosen, dict) else {}
    memory_proof = memory_proof or {}
    updates: dict[str, dict[str, Any]] = {}
    for area_id in set(vibe_candidates) | set(chosen):
        lines = vibe_candidates.get(area_id, [])
        pick = chosen.get(area_id) if isinstance(chosen.get(area_id), dict) else {}
        by_id = {line["id"]: line.get("evidence") or [] for line in lines}
        sources = [item for item in pick.get("from") or [] if isinstance(item, str)]
        proof = [evidence for item in sources for evidence in by_id.get(item) or memory_proof.get(item) or []]
        text = str(pick.get("line") or "").strip()
        if (not proof or not text) and lines:
            best = max(lines, key=lambda line: len(line.get("evidence") or []))
            proof, text = best.get("evidence") or [], best["text"]
        if proof and text:
            unique = {(item["conversation_id"], item["message_index"]): item for item in proof}
            updates[area_id] = {"text": text, "evidence": list(unique.values())}
    return updates


def _shared_context(user_id: str, whole: MemoryBatch) -> dict[str, Any]:
    """What the merge sees: existing memories, the card and the vibe card, read once."""
    user_text = " ".join(message.content for message in whole.new_messages if message.role == "user")
    return {
        "memories": existing_memory_context(user_id, 3, user_text),
        "timezone": get_user_timezone(user_id),
        "card": get_user_card(user_id) or "",
        "vibe": get_vibe_card(user_id),
    }


def mark_upload_progress(source_id: str, user_id: str, **changes: Any) -> None:
    """For the job that finishes an upload after reading (indexing, done)."""
    _progress(source_id, user_id, **changes)


def _progress(source_id: str, user_id: str, **changes: Any) -> None:
    """Keep the upload's reading progress in its metadata; never fails the read."""
    if not source_id:
        return
    try:
        current = (get_context_source_metadata(source_id, user_id) or {}).get("reading") or {}
        update_context_source_metadata(source_id, user_id, {"reading": {**current, **changes, "updated_at": utc_now_iso()}})
    except Exception as error:
        logger.warning("agent.upload_read.progress_failed error_type=%s", type(error).__name__)


__all__ = [
    "DEFAULT_UPLOAD_MODEL",
    "MAX_PARTS",
    "PART_USER_LINES",
    "card_lines",
    "chat_partner",
    "memory_proof",
    "merge_model",
    "mark_upload_progress",
    "merge_vibe",
    "read_upload",
    "upload_model",
    "upload_parts",
]
