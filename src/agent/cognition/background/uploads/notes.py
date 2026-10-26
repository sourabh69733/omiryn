"""Checks the notes a model wrote about an uploaded chat and builds the stored digest from them.

Pure functions, no model calls: every cited line must exist in the part it came from, memories go
through the normal memory validation, and the merge's choices (ids) are turned into memories with
joined proof and a digest whose topics carry their real lines and dates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any
from zoneinfo import ZoneInfo

from agent.memory_engine.memories.models import MemoryKind, MemoryPurpose, MemorySensitivity
from agent.memory_engine.memories.operations import (
    MemoryAddProposal,
    MemoryReinforceProposal,
    MemorySupersedeProposal,
)
from agent.memory_engine.memories.validation import validate_memory_analysis_v3
from agent.memory_engine.memories.vibe import VIBE_AREAS, validate_vibe_updates
from agent.memory_engine.processing.models import MemoryBatch
from agent.shared.timeline import parse_time

from agent.cognition.background.memory_run.coordination import _user_message_resolver

MAX_THREADS = 12
_TEXT_LIMITS = {"title": 80, "summary": 400, "user_view": 300, "other_view": 300, "fact": 240, "what": 200, "when": 40}


@dataclass(frozen=True)
class PartNotes:
    """What one part of an upload showed, already checked."""

    memories: tuple[MemoryAddProposal, ...] = ()
    threads: tuple[dict[str, Any], ...] = ()
    about_other: tuple[dict[str, Any], ...] = ()
    plans: tuple[dict[str, Any], ...] = ()
    dynamics: str | None = None
    vibe: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not (self.memories or self.threads or self.about_other or self.plans)


def part_input(part: MemoryBatch, partner: str | None, zone: ZoneInfo) -> dict[str, Any]:
    """What the part reader sees: both sides, with indexes to cite and local times."""
    messages = []
    for message in part.messages:
        sent = parse_time(message.sent_at)
        messages.append(
            {
                "i": message.message_index,
                "from": "user" if message.role == "user" else (message.speaker or partner or "other"),
                "at": sent.astimezone(zone).isoformat(timespec="minutes") if sent else None,
                "text": message.content,
                **({"new": False} if message.scope != "new" else {}),
            }
        )
    return {
        "user_timezone": zone.key,
        "chat_with": partner,
        "vibe_areas": [{"id": area_id, "meaning": goal} for area_id, _, goal in VIBE_AREAS],
        "messages": messages,
    }


def check_part(raw: Any, part: MemoryBatch) -> PartNotes:
    """Keep only what is well formed and cites this part's own new lines."""
    raw = raw if isinstance(raw, dict) else {}
    cited = {message.message_index for message in part.messages if message.scope == "new"}

    def lines(value: Any) -> list[int]:
        return sorted({item for item in value or [] if isinstance(item, int) and not isinstance(item, bool) and item in cited}) if isinstance(value, list) else []

    def items(key: str, fields: tuple[str, ...], required: str) -> tuple[dict[str, Any], ...]:
        kept = []
        for item in raw.get(key) or []:
            if not isinstance(item, dict):
                continue
            entry = {name: _text(item.get(name), name) for name in fields}
            entry["lines"] = lines(item.get("lines"))
            if entry[required] and entry["lines"]:
                kept.append(entry)
        return tuple(kept)

    adds = [
        operation
        for operation in raw.get("about_user") or []
        if isinstance(operation, dict) and operation.get("operation") == "add" and operation.get("memory_kind") != "procedural"
    ]
    memories = validate_memory_analysis_v3({"operations": adds}, batch=part).operations
    return PartNotes(
        memories=tuple(memory for memory in memories if isinstance(memory, MemoryAddProposal)),
        threads=items("threads", ("title", "summary", "user_view", "other_view"), "title"),
        about_other=items("about_other", ("fact",), "fact"),
        plans=items("plans", ("what", "when"), "what"),
        dynamics=_text(raw.get("dynamics"), "summary"),
        vibe=validate_vibe_updates(raw.get("vibe"), resolve_evidence=_user_message_resolver(part)),
    )


@dataclass(frozen=True)
class Gathered:
    """Every part's notes with the ids the merge refers to (c.., t.., o.., p.., v..)."""

    candidates: list[tuple[str, MemoryAddProposal]]
    threads: dict[str, dict[str, Any]]
    about_other: dict[str, dict[str, Any]]
    plans: dict[str, dict[str, Any]]
    dynamics: list[str]
    vibe: dict[str, list[dict[str, Any]]]


def gather(notes: list[PartNotes]) -> Gathered:
    candidates: list[tuple[str, MemoryAddProposal]] = []
    threads: dict[str, dict[str, Any]] = {}
    about_other: dict[str, dict[str, Any]] = {}
    plans: dict[str, dict[str, Any]] = {}
    vibe: dict[str, list[dict[str, Any]]] = {}
    count = 0
    for part in notes:
        candidates += [(f"c{len(candidates) + 1}", memory) for memory in part.memories]
        threads.update({f"t{len(threads) + index + 1}": item for index, item in enumerate(part.threads)})
        about_other.update({f"o{len(about_other) + index + 1}": item for index, item in enumerate(part.about_other)})
        plans.update({f"p{len(plans) + index + 1}": item for index, item in enumerate(part.plans)})
        for area_id, line in part.vibe.items():
            count += 1
            vibe.setdefault(area_id, []).append({"id": f"v{count}", **line})
    return Gathered(candidates, threads, about_other, plans, [part.dynamics for part in notes if part.dynamics], vibe)


def merge_input(gathered: Gathered, *, partner: str | None, dates: dict[str, str | None], card: str, memories: list[dict[str, Any]], vibe: dict[str, str]) -> dict[str, Any]:
    without_lines = lambda item: {key: value for key, value in item.items() if key != "lines" and value}  # noqa: E731
    return {
        "chat_with": partner,
        "chat_dates": dates,
        "current_user_card": card,
        "existing_memories": [
            {"id": memory["id"], "statement": memory.get("statement") or str(memory.get("value"))}
            for memory in memories
            if memory.get("targetable") is not False
        ][:60],
        "candidates": [{"id": cid, "kind": memory.kind.value, "statement": memory.statement or str(memory.value)} for cid, memory in gathered.candidates],
        "threads": [{"id": tid, **without_lines(item)} for tid, item in gathered.threads.items()],
        "about_other": [{"id": oid, "fact": item["fact"]} for oid, item in gathered.about_other.items()],
        "plans": [{"id": pid, **without_lines(item)} for pid, item in gathered.plans.items()],
        "dynamics": gathered.dynamics,
        "vibe_areas": [{"id": area_id, "meaning": goal} for area_id, _, goal in VIBE_AREAS],
        "current_vibe": vibe,
        "vibe_candidates": {area_id: [{"id": line["id"], "line": line["text"]} for line in lines] for area_id, lines in gathered.vibe.items()},
    }


def merged_memories(gathered: Gathered, merge: dict[str, Any], existing: list[dict[str, Any]]) -> tuple[Any, ...]:
    """One memory per group of candidates that say the same thing; an existing one is reinforced."""
    known_ids = {str(memory["id"]) for memory in existing if memory.get("targetable") is not False}
    by_id = dict(gathered.candidates)
    leader: dict[str, str] = {}
    for group in merge.get("same") or []:
        ids = [item for item in group if item in by_id and item not in leader] if isinstance(group, list) else []
        for cid in ids:
            leader[cid] = ids[0]
    known: dict[str, str] = {}
    for item in merge.get("known") or []:
        if isinstance(item, dict) and item.get("candidate") in by_id and str(item.get("memory")) in known_ids:
            known[leader.get(item["candidate"], item["candidate"])] = str(item["memory"])
    groups: dict[str, list[MemoryAddProposal]] = {}
    for cid, memory in gathered.candidates:
        groups.setdefault(leader.get(cid, cid), []).append(memory)
    operations: list[Any] = []
    reinforced: set[str] = set()
    for head, members in groups.items():
        proof = tuple(sorted({index for member in members for index in member.evidence_message_indexes}))
        confidence = max(member.confidence for member in members)
        importance = max(member.importance for member in members)
        target = known.get(head)
        if target and target not in reinforced:
            reinforced.add(target)
            operations.append(MemoryReinforceProposal(target_memory_id=target, confidence=confidence, importance=importance, evidence_message_indexes=proof))
        elif not target:
            best = max(members, key=lambda member: len(member.statement or str(member.value)))
            operations.append(replace(best, evidence_message_indexes=proof, confidence=confidence, importance=importance, focus=any(m.focus for m in members)))
    return tuple(operations)


def relationship_memory(partner: str | None, merge: dict[str, Any], gathered: Gathered, whole: MemoryBatch, existing: list[dict[str, Any]]) -> tuple[Any, ...]:
    """Who the chat was with and what they talk about, proven by the user's own lines.

    What they talk about must rest on notes from this upload; without any, only the plain fact.
    An earlier memory about the same person is replaced, so re-uploading does not add a copy.
    """
    if not partner:
        return ()
    written = merge.get("relationship") if isinstance(merge.get("relationship"), dict) else {}
    user_lines = {message.message_index for message in whole.messages if message.role == "user"}
    proof = sorted({index for ref in written.get("from") or [] for index in _user_lines(ref, gathered, user_lines)})
    statement = " ".join(str(written.get("statement") or "").split())[:240] if proof else ""
    if not statement:
        statement, proof = f"Chats with {partner} on WhatsApp.", sorted(user_lines)[:3]
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


def build_digest(partner: str | None, merge: dict[str, Any], gathered: Gathered, whole: MemoryBatch) -> dict[str, Any]:
    """The stored digest: summary, index line, topics, the other person, plans; every item with lines."""
    sent = {message.message_index: parse_time(message.sent_at) for message in whole.messages}
    threads = _chosen(merge.get("threads"), gathered.threads, ("title", "summary", "user_view", "other_view"), "title")
    if not threads:  # the merge failed to write topics: keep the parts' own
        threads = [dict(item) for item in gathered.threads.values()]
    for thread in threads:
        days = sorted(moment for moment in (sent.get(index) for index in thread["lines"]) if moment)
        thread["started"] = days[0].date().isoformat() if days else None
        thread["ended"] = days[-1].date().isoformat() if days else None
    threads.sort(key=lambda thread: len(thread["lines"]), reverse=True)
    person = _chosen(merge.get("person"), gathered.about_other, ("text",), "text", source_text="fact")
    plans = _chosen(merge.get("plans"), gathered.plans, ("what", "when"), "what")
    summary = _text(merge.get("summary"), "summary") or ""
    index_line = _text(merge.get("index_line"), "title") or (partner or "Shared notes")
    moments = [moment for moment in sent.values() if moment]
    return {
        "chat_with": partner,
        "chat_dates": {
            "from": min(moments).date().isoformat() if moments else None,
            "to": max(moments).date().isoformat() if moments else None,
        },
        "message_count": len(whole.messages),
        "summary": summary,
        "index_line": index_line,
        "threads": threads[:MAX_THREADS],
        "person": person,
        "plans": plans,
        "dynamics": gathered.dynamics[:3],
    }


def chat_dates(whole: MemoryBatch) -> dict[str, str | None]:
    moments = sorted(moment for moment in (parse_time(message.sent_at) for message in whole.messages) if moment)
    return {"from": moments[0].date().isoformat() if moments else None, "to": moments[-1].date().isoformat() if moments else None}


def _chosen(
    written: Any,
    sources: dict[str, dict[str, Any]],
    fields: tuple[str, ...],
    required: str,
    *,
    source_text: str | None = None,
) -> list[dict[str, Any]]:
    """Merged items with the lines of the notes they came from; items citing no note are dropped."""
    kept = []
    for item in written if isinstance(written, list) else []:
        if not isinstance(item, dict):
            continue
        refs = [ref for ref in item.get("from") or [] if isinstance(ref, str) and ref in sources]
        line_set = sorted({index for ref in refs for index in sources[ref]["lines"]})
        entry = {name: _text(item.get(name), name) for name in fields}
        if not entry[required] and source_text and len(refs) == 1:
            entry[required] = sources[refs[0]].get(source_text)
        if entry[required] and line_set:
            kept.append({**entry, "lines": line_set})
    return kept


def _user_lines(ref: Any, gathered: Gathered, user_lines: set[int]) -> list[int]:
    by_candidate = dict(gathered.candidates)
    if ref in by_candidate:
        return list(by_candidate[ref].evidence_message_indexes)
    if ref in gathered.threads:
        return [index for index in gathered.threads[ref]["lines"] if index in user_lines]
    return []


def _text(value: Any, name: str) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text[: _TEXT_LIMITS.get(name, 300)] or None


__all__ = [
    "Gathered",
    "PartNotes",
    "build_digest",
    "chat_dates",
    "check_part",
    "gather",
    "merge_input",
    "merged_memories",
    "part_input",
    "relationship_memory",
]
