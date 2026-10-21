"""Reads an uploaded chat in about a minute: its parts at the same time, then one short wrap-up.

The normal path reads a chat 7 user lines per run, one run after another (about 50 s each), so a
150-line upload took around 20 minutes. Here every part (about 30 user lines) goes to the same
background prompt at once, which leaves out what only a live chat needs. A wrap-up call then groups
memories that several parts learned, and writes the card and vibe lines once. Everything is saved
in one batch over the whole hidden chat, after all parts are read, so a retry starts clean.

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

from agent.memory_engine.memories.embeddings import index_agent_memories
from agent.memory_engine.memories.focus import without_focus_lines
from agent.memory_engine.memories.models import MemoryKind, MemoryPurpose, MemorySensitivity
from agent.memory_engine.memories.operations import (
    MemoryAddProposal,
    MemoryAnalysisV3,
    MemorySupersedeProposal,
)
from agent.memory_engine.memories.application import apply_validated_memory_analysis_v3
from agent.memory_engine.memories.user_card import validate_user_card, without_replaced_lines
from agent.memory_engine.memories.vibe import VIBE_AREAS, rejected_texts, vibe_texts
from agent.memory_engine.processing.context import build_memory_batch
from agent.memory_engine.processing.models import MemoryBatch, MemoryHandoff, MemoryProcessingState
from agent.memory_engine.processing.service import (
    claim_user_lease,
    get_processing_state,
    release_user_lease,
    save_processing_state,
)
from agent.providers import analyze_background_cognition, analyze_upload_wrap_up
from agent.shared.clock import utc_now_iso
from storage import get_user_card, get_user_timezone, list_agent_memories
from storage.context_sources import get_context_source_metadata, update_context_source_metadata
from storage.user_cards import set_user_card
from storage.vibe_cards import get_vibe_card

from .coordination import interpret_background_cognition
from .prompt import background_cognition_prompt
from .service import (
    _apply_vibe,
    _context_overlap,
    _existing_memory_context,
    _replaced_memory_ids,
    _timeout_seconds,
)

logger = logging.getLogger(__name__)

# User lines per part; a bigger upload gets bigger parts so at most MAX_PARTS run at once. Output
# speed is the limit (each memory is a long JSON object), so smaller parts finish sooner.
PART_USER_LINES = int(os.getenv("MEMORY_UPLOAD_PART_LINES", "30"))
MAX_PARTS = int(os.getenv("MEMORY_UPLOAD_MAX_PARTS", "6"))
_EVERY_LINE = 10**9


async def read_upload(conversation: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Learn from a whole uploaded chat; raises on failure so the job retries from the start."""
    conversation_id = str(conversation["id"])
    source_id = str(conversation.get("import_source_id") or "")
    messages = list(conversation.get("messages") or [])
    lease = claim_user_lease(user_id, conversation_id, lease_seconds=_timeout_seconds() * 2 + 60)
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
            _progress(source_id, user_id, state="done", parts=0, parts_done=0, learned=0)
            return {"status": "no_pending_messages", "operation_count": 0}
        _progress(source_id, user_id, state="reading", parts=len(parts), parts_done=0, learned=0)
        model = upload_model()
        context = _shared_context(user_id, whole)
        done = 0

        async def read(part: MemoryBatch) -> Any:
            nonlocal done
            cognition = await _read_part(part, context, model)
            done += 1
            _progress(source_id, user_id, parts_done=done)
            return cognition

        cognitions = await asyncio.gather(*(read(part) for part in parts))
        _progress(source_id, user_id, state="merging")
        candidates, others, vibe_candidates = _collect(cognitions)
        partner = chat_partner(whole)
        wrap = await _wrap_up(conversation_id, candidates, vibe_candidates, context, model, partner)
        operations = merge_operations(candidates, others, wrap.get("same"))
        operations += partner_memory(partner, wrap.get("chat_with"), candidates, whole, context["memories"])
        if operations:
            applied = apply_validated_memory_analysis_v3(
                whole,
                MemoryAnalysisV3(decision="propose", operations=operations, handoff=MemoryHandoff(), valid=True),
                extractor_model=model,
            )
            learned = applied.applied_count
        else:
            applied, learned = None, 0
        # Saved before the card and vibe, so a retry never applies the memories twice.
        state = get_processing_state(conversation_id, user_id) or MemoryProcessingState(
            conversation_id=conversation_id, user_id=user_id
        )
        save_processing_state(
            replace(state, processed_through_message_index=whole.new_end_message_index, last_batch_key=whole.batch_key)
        )
        await _save_after(whole, applied, operations, wrap, vibe_candidates, candidates, context)
        seconds = round(monotonic() - started, 1)
        _progress(source_id, user_id, state="done", learned=learned, seconds=seconds)
        logger.info("agent.upload_read conversation_id=%s parts=%s learned=%s seconds=%s", conversation_id, len(parts), learned, seconds)
        return {"status": "upload_read", "parts": len(parts), "applied_count": learned, "seconds": seconds, "operation_count": len(operations)}
    except Exception:
        _progress(source_id, user_id, state="failed")
        raise
    finally:
        release_user_lease(user_id, lease)


# On a 150-line upload (2026-10-21): Qwen3-Next 80B read it in ~25 s with the same facts as
# Qwen3 235B, which took ~170 s (it writes ~17 tokens a second; more parts only made it slower).
DEFAULT_UPLOAD_MODEL = "Qwen/Qwen3-Next-80B-A3B-Instruct"


def upload_model() -> str | None:
    """MEMORY_UPLOAD_MODEL, else a fast default on DeepInfra, else the background model."""
    configured = os.getenv("MEMORY_UPLOAD_MODEL", "").strip()
    if configured:
        return configured
    if os.getenv("AGENT_PROVIDER", "").strip().lower() == "deepinfra":
        return DEFAULT_UPLOAD_MODEL
    return os.getenv("MEMORY_BACKGROUND_V2_MODEL", "").strip() or None


def upload_parts(conversation_id: str, user_id: str, messages: list[dict[str, Any]]) -> list[MemoryBatch]:
    """The upload split into parts of about PART_USER_LINES user lines, at most MAX_PARTS."""
    user_lines = sum(1 for message in messages if message.get("role") == "user")
    per_part = max(PART_USER_LINES, math.ceil(user_lines / MAX_PARTS))
    parts: list[MemoryBatch] = []
    cursor = -1
    while True:
        batch = build_memory_batch(
            conversation_id=conversation_id,
            user_id=user_id,
            messages=messages,
            state=MemoryProcessingState(
                conversation_id=conversation_id, user_id=user_id, processed_through_message_index=cursor
            ),
            context_overlap=_context_overlap(),
            max_meaningful_user_messages=per_part,
        )
        if batch is None:
            return parts
        if batch.meaningful_user_message_count:
            parts.append(batch)
        cursor = batch.new_end_message_index


def merge_operations(
    candidates: list[tuple[str, MemoryAddProposal]],
    others: dict[str, Any],
    same: Any,
) -> tuple[Any, ...]:
    """One memory per group of candidates that say the same thing, with all their proof."""
    known = {candidate_id for candidate_id, _ in candidates}
    leader: dict[str, str] = {}
    for group in same if isinstance(same, list) else []:
        ids = [item for item in group if item in known and item not in leader] if isinstance(group, list) else []
        for candidate_id in ids:
            leader[candidate_id] = ids[0]
    groups: dict[str, list[MemoryAddProposal]] = {}
    for candidate_id, proposal in candidates:
        groups.setdefault(leader.get(candidate_id, candidate_id), []).append(proposal)
    merged = []
    for members in groups.values():
        best = max(members, key=lambda proposal: len(proposal.statement or str(proposal.value)))
        merged.append(
            replace(
                best,
                evidence_message_indexes=tuple(sorted({index for member in members for index in member.evidence_message_indexes})),
                confidence=max(member.confidence for member in members),
                importance=max(member.importance for member in members),
                focus=any(member.focus for member in members),
            )
        )
    return tuple(merged) + tuple(others.values())


def _collect(cognitions: list[Any]) -> tuple[list[tuple[str, MemoryAddProposal]], dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """New memories with candidate IDs, changes to existing ones (one per memory), vibe lines."""
    candidates: list[tuple[str, MemoryAddProposal]] = []
    others: dict[str, Any] = {}
    vibe: dict[str, list[dict[str, Any]]] = {}
    for cognition in cognitions:
        for operation in cognition.memory.operations:
            if isinstance(operation, MemoryAddProposal):
                # Nothing in an upload was said to Omi, so it holds no how-to-talk request.
                if operation.kind != MemoryKind.PROCEDURAL:
                    candidates.append((f"c{len(candidates) + 1}", operation))
            elif operation.target_memory_id not in others or isinstance(operation, MemorySupersedeProposal):
                others[operation.target_memory_id] = operation
        for area_id, line in (cognition.vibe or {}).items():
            vibe.setdefault(area_id, []).append({"id": f"v{sum(map(len, vibe.values())) + 1}", **line})
    return candidates, others, vibe


# Waits before each retry of a part. The provider answers "model busy" (429) under load, so an
# instant retry fails too; the last try uses the background model instead of the fast one.
RETRY_WAITS = (5.0, 15.0)


def _attempt_models(model: str | None) -> list[str | None]:
    fallback = os.getenv("MEMORY_BACKGROUND_V2_MODEL", "").strip() or None
    return [model] * len(RETRY_WAITS) + [fallback if fallback and fallback != model else model]


async def _read_part(part: MemoryBatch, context: dict[str, Any], model: str | None) -> Any:
    """One part through the normal background prompt, retried with waits and a fallback model."""
    error: Exception = RuntimeError("part was not read")
    for attempt, attempt_model in enumerate(_attempt_models(model)):
        if attempt:
            await asyncio.sleep(RETRY_WAITS[min(attempt, len(RETRY_WAITS)) - 1])
        try:
            raw = await analyze_background_cognition(
                background_cognition_prompt(
                    part,
                    context["memories"],
                    [],
                    context["timezone"],
                    context["card"],
                    None,
                    vibe_texts(context["vibe"]["areas"]) if context["vibe"] else None,
                    rejected_texts(context["vibe"].get("rejected")) if context["vibe"] else None,
                    None,
                ),
                conversation_id=part.conversation_id,
                model=attempt_model,
                timeout_seconds=_timeout_seconds(),
                memory_version=3,
            )
            cognition = interpret_background_cognition(
                raw,
                batch=part,
                existing_memory_ids={str(memory["id"]) for memory in context["memories"] if memory.get("targetable") is not False},
                thread_candidates=[],
                memory_version=3,
                active_self_note_ids=set(),
                open_question_ids=set(),
            )
            if cognition.memory.valid:
                return cognition
            error = ValueError("; ".join(cognition.memory.errors)[:300])
        except Exception as caught:  # provider or parse failure
            error = caught
        logger.warning("agent.upload_read.part_failed attempt=%s error_type=%s", attempt + 1, type(error).__name__)
    raise error


async def _wrap_up(
    conversation_id: str,
    candidates: list[tuple[str, MemoryAddProposal]],
    vibe_candidates: dict[str, list[dict[str, Any]]],
    context: dict[str, Any],
    model: str | None,
    partner: str | None = None,
) -> dict[str, Any]:
    payload = {
        "chat_with": partner,
        "candidates": [
            {"id": candidate_id, "kind": proposal.kind.value, "statement": proposal.statement or str(proposal.value)}
            for candidate_id, proposal in candidates
        ],
        "current_user_card": context["card"],
        "vibe_areas": [{"id": area_id, "meaning": goal} for area_id, _, goal in VIBE_AREAS],
        "current_vibe": vibe_texts(context["vibe"]["areas"]) if context["vibe"] else {},
        "vibe_candidates": {
            area_id: [{"id": line["id"], "line": line["text"]} for line in lines] for area_id, lines in vibe_candidates.items()
        },
    }
    text = json.dumps(payload, ensure_ascii=False)
    models = _attempt_models(model)
    for attempt, attempt_model in enumerate(models):
        if attempt:
            await asyncio.sleep(RETRY_WAITS[min(attempt, len(RETRY_WAITS)) - 1])
        try:
            raw = await analyze_upload_wrap_up(text, conversation_id=conversation_id, model=attempt_model)
            return raw if isinstance(raw, dict) else {}
        except Exception as error:
            if attempt == len(models) - 1:
                raise
            logger.warning("agent.upload_read.wrap_up_failed attempt=%s error_type=%s", attempt + 1, type(error).__name__)
    return {}


async def _save_after(
    whole: MemoryBatch,
    applied: Any,
    operations: tuple[Any, ...],
    wrap: dict[str, Any],
    vibe_candidates: dict[str, list[dict[str, Any]]],
    candidates: list[tuple[str, MemoryAddProposal]],
    context: dict[str, Any],
) -> None:
    """Embeddings, card and vibe; each is best effort, the memories are already saved."""
    user_id = whole.user_id
    if applied is not None:
        try:
            await index_agent_memories(applied.memories, conversation_id=whole.conversation_id)
        except Exception as error:
            logger.warning("agent.upload_read.index_failed error_type=%s", type(error).__name__)
    card = validate_user_card(card_lines(wrap.get("user_card")))
    replaced_ids = _replaced_memory_ids(operations)
    if card or replaced_ids:
        memories = list_agent_memories(user_id)
        focus = [memory for memory in memories if memory.get("focus") and memory.get("status") == "active"]
        replaced = [(memory, replaced_ids[memory["id"]]) for memory in memories if memory["id"] in replaced_ids]
        new_card = without_replaced_lines(without_focus_lines(card or context["card"], focus), replaced)
        if new_card != context["card"]:
            set_user_card(user_id, new_card)
    updates = merge_vibe(wrap.get("vibe"), vibe_candidates, memory_proof(whole, candidates))
    if updates and context["vibe"] is not None:
        await _apply_vibe(whole, context["vibe"], updates)


def chat_partner(whole: MemoryBatch) -> str | None:
    """Who the user was chatting with: the other person with the most lines, None for notes."""
    counts: dict[str, int] = {}
    for message in whole.messages:
        if message.role == "other" and message.speaker:
            counts[message.speaker] = counts.get(message.speaker, 0) + 1
    return max(counts, key=counts.__getitem__) if counts else None


def partner_memory(
    partner: str | None,
    written: Any,
    candidates: list[tuple[str, MemoryAddProposal]],
    whole: MemoryBatch,
    existing: list[dict[str, Any]],
) -> tuple[Any, ...]:
    """One relationship memory about who the chat was with, proven by the user's own lines.

    The upload itself shows they talk; what about comes from the wrap-up. An earlier memory about
    the same person is replaced, so a second upload of that chat does not add a copy.
    """
    if not partner:
        return ()
    written = written if isinstance(written, dict) else {}
    by_id = dict(candidates)
    proof = sorted({index for item in written.get("from") or [] if item in by_id for index in by_id[item].evidence_message_indexes})
    # What they talk about must come from memories learned here; without any, only the plain fact.
    statement = " ".join(str(written.get("statement") or "").split())[:240] if proof else ""
    if not statement:
        statement = f"Chats with {partner} on WhatsApp."
        proof = [message.message_index for message in whole.messages if message.role == "user"][:3]
    key = "chat_partner." + re.sub(r"[^a-z0-9]+", "_", partner.lower()).strip("_")
    memory = MemoryAddProposal(
        kind=MemoryKind.RELATIONSHIP,
        purposes=frozenset({MemoryPurpose.PERSONALIZATION}),
        key=key,
        value=statement,
        sensitivity=MemorySensitivity.STANDARD,
        confidence=0.85,
        importance=0.6,
        evidence_message_indexes=tuple(proof[:8]),
        statement=statement,
    )
    earlier = next((item for item in existing if item.get("key") == key and item.get("targetable") is not False), None)
    return (MemorySupersedeProposal(target_memory_id=str(earlier["id"]), replacement=memory),) if earlier else (memory,)


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

    A line without proof is never kept (the proof check would drop it anyway). When the wrap-up
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
    """What every part sees: existing memories, the card and the vibe card, read once."""
    user_text = " ".join(message.content for message in whole.new_messages if message.role == "user")
    return {
        "memories": _existing_memory_context(user_id, 3, user_text),
        "timezone": get_user_timezone(user_id),
        "card": get_user_card(user_id) or "",
        "vibe": get_vibe_card(user_id),
    }


def _progress(source_id: str, user_id: str, **changes: Any) -> None:
    """Keep the upload's reading progress in its metadata; never fails the read."""
    if not source_id:
        return
    try:
        current = (get_context_source_metadata(source_id, user_id) or {}).get("reading") or {}
        update_context_source_metadata(source_id, user_id, {"reading": {**current, **changes, "updated_at": utc_now_iso()}})
    except Exception as error:
        logger.warning("agent.upload_read.progress_failed error_type=%s", type(error).__name__)


__all__ = ["DEFAULT_UPLOAD_MODEL", "MAX_PARTS", "PART_USER_LINES", "card_lines", "chat_partner", "memory_proof", "merge_operations", "merge_vibe", "partner_memory", "read_upload", "upload_parts"]
