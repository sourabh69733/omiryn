"""The user's friend vibe: what the companion understands about who they'd get along with.

Background cognition writes one short line per area from what the user actually said. Code only
validates the shape and counts filled areas into milestones; it never decides what to ask.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

# (id, stage, goal). The goal tells the models what the area means; it is not a question to ask.
VIBE_AREAS: tuple[tuple[str, str, str], ...] = (
    ("friend_wish", "basics", "what they want from a friend and what a good friendship feels like to them"),
    ("humor", "basics", "what makes them laugh and how they joke"),
    ("social_energy", "basics", "quiet or loud, small group or crowd, planned or spontaneous"),
    ("interests", "basics", "what they love doing or could talk about for hours"),
    ("daily_life", "basics", "what fills their days (study, work, routine) and when they have free time"),
    ("values", "deeper", "beliefs and views they care about: god, caste, politics, work, money"),
    ("stories", "deeper", "experiences that shaped them, or stories they relate to"),
    ("accepts", "deeper", "differences in a friend they are fine with"),
    ("deal_breakers", "deeper", "what they cannot stand in a friend"),
    ("conflict", "deeper", "how they handle disagreement or hurt"),
    ("keeping_in_touch", "deeper", "how they like to stay in touch and how often"),
)
VIBE_AREA_IDS = tuple(area_id for area_id, _, _ in VIBE_AREAS)
BASIC_AREA_IDS = tuple(area_id for area_id, stage, _ in VIBE_AREAS if stage == "basics")
DEEPER_AREA_IDS = tuple(area_id for area_id, stage, _ in VIBE_AREAS if stage == "deeper")
VIBE_AREA_GOALS = {area_id: goal for area_id, _, goal in VIBE_AREAS}
MAX_VIBE_LINE_CHARS = 220
MAX_VIBE_UPDATES = 4

# How a vibe line is written; shared by the live background prompt and the backfill.
VIBE_LINE_RULES = """- A line is one or two plain English sentences, folding in the current line, even when the chat
  is in Hindi or Hinglish: "<what they said, specific>". Describe; do not paste their words. Write
  what they showed, not a label: not "funny", but what makes them laugh.
- Only what the user said or plainly showed about themselves. Never guess from one word, never from
  the companion's messages, and never fill an area just because it is empty.
- A line needs a clear statement from the user about themselves, or a pattern across several
  messages. A filler phrase ("chill", "pata nahi", "kal baat karenge"), a passing mood or a
  reaction to the companion is not enough. A short chat rarely shows more than one or two areas.
- Preferences about a dating or marriage partner are not friend preferences; leave them out unless
  the user said they apply to friends too.
- Never health, mental health, sexual or financial details, even when the user shared them."""

# In order. "ready_to_match" is what matching will wait for.
VIBE_MILESTONES = ("starting", "first_impressions", "basics", "ready_to_match", "deep")
VIBE_MILESTONE_MEANINGS = {
    "starting": "just getting to know them",
    "first_impressions": "a first sense of their vibe",
    "basics": "the basics of what they want in friends",
    "ready_to_match": "enough to start looking for friends they'd get along with",
    "deep": "a deep understanding of their friend vibe",
}


# A line is {"text": str, "evidence": [{"conversation_id", "message_index", "sent_at"?}]}. The
# evidence is the user messages behind it: code checks each is a real user message, and a second
# model call checks it really shows the line. Older cards stored a bare string (no evidence).
MAX_VIBE_EVIDENCE = 8
# Different days the user said it before a line counts as clear: a pattern, not one moment.
CLEAR_DAY_COUNT = 2

# Turns a model's evidence reference (an index or id) into an evidence item, or None when it does
# not point at a user message the model was shown.
EvidenceResolver = Callable[[Any], "dict[str, Any] | None"]


@dataclass(frozen=True)
class VibeProgress:
    milestone: str
    known: tuple[str, ...]
    clear: tuple[str, ...]
    open: tuple[str, ...]
    basics_known: int
    deeper_known: int

    @property
    def mentioned(self) -> tuple[str, ...]:
        return tuple(area_id for area_id in self.known if area_id not in self.clear)

    @property
    def next_milestone(self) -> str | None:
        position = VIBE_MILESTONES.index(self.milestone)
        return VIBE_MILESTONES[position + 1] if position + 1 < len(VIBE_MILESTONES) else None


def line_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("text") or "")
    return value if isinstance(value, str) else ""


def line_evidence(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    return [
        {
            "conversation_id": str(item["conversation_id"]),
            "message_index": int(item["message_index"]),
            **({"sent_at": item["sent_at"]} if isinstance(item.get("sent_at"), str) else {}),
        }
        for item in value.get("evidence") or []
        if isinstance(item, dict) and item.get("conversation_id") and isinstance(item.get("message_index"), int)
    ]


def evidence_days(value: Any) -> int:
    """Distinct days (UTC) the cited messages were sent; proof without a time adds none."""
    return len({item["sent_at"][:10] for item in line_evidence(value) if item.get("sent_at")})


def line_strength(value: Any) -> str:
    return "clear" if evidence_days(value) >= CLEAR_DAY_COUNT else "mentioned"


def _evidence_key(item: dict[str, Any]) -> tuple[str, int]:
    return item["conversation_id"], item["message_index"]


def vibe_texts(card: dict[str, Any] | None) -> dict[str, str]:
    """Just the lines, for prompts."""
    return {area_id: line_text(value) for area_id, value in (card or {}).items() if line_text(value)}


def vibe_progress(card: dict[str, Any] | None) -> VibeProgress:
    """First impressions count any line; later milestones count only clear lines."""
    card = card or {}
    known = tuple(area_id for area_id in VIBE_AREA_IDS if line_text(card.get(area_id)))
    clear = tuple(area_id for area_id in known if line_strength(card[area_id]) == "clear")
    basics = sum(area_id in clear for area_id in BASIC_AREA_IDS)
    deeper = sum(area_id in clear for area_id in DEEPER_AREA_IDS)
    if len(clear) == len(VIBE_AREA_IDS):
        milestone = "deep"
    elif basics == len(BASIC_AREA_IDS) and deeper >= 3:
        milestone = "ready_to_match"
    elif basics == len(BASIC_AREA_IDS):
        milestone = "basics"
    elif len(known) >= 2:
        milestone = "first_impressions"
    else:
        milestone = "starting"
    return VibeProgress(
        milestone=milestone,
        known=known,
        clear=clear,
        open=tuple(area_id for area_id in VIBE_AREA_IDS if area_id not in known),
        basics_known=basics,
        deeper_known=deeper,
    )


def validate_vibe_updates(
    raw: Any,
    *,
    resolve_evidence: EvidenceResolver,
    max_updates: int = MAX_VIBE_UPDATES,
) -> dict[str, dict[str, Any]]:
    """Area lines the model wrote, each backed by at least one real user message.

    Unknown areas, empty lines, and lines whose evidence does not resolve to a user message (a
    companion message, an unknown index, nothing at all) are dropped.
    """
    if not isinstance(raw, dict):
        return {}
    updates: dict[str, dict[str, Any]] = {}
    for area_id, value in raw.items():
        if area_id not in VIBE_AREA_GOALS or not isinstance(value, dict):
            continue
        line = " ".join(str(value.get("line") or "").split())
        refs = value.get("evidence")
        if not line or not isinstance(refs, list):
            continue
        evidence: list[dict[str, Any]] = []
        for ref in refs:
            resolved = resolve_evidence(ref)
            if resolved and all(_evidence_key(item) != _evidence_key(resolved) for item in evidence):
                evidence.append(resolved)
        if not evidence:
            continue
        if len(line) > MAX_VIBE_LINE_CHARS:
            line = line[:MAX_VIBE_LINE_CHARS].rsplit(" ", 1)[0]
        updates[area_id] = {"text": line, "evidence": evidence[:MAX_VIBE_EVIDENCE]}
        if len(updates) >= max_updates:
            break
    return updates


def rejected_texts(rejected: dict[str, Any] | None) -> dict[str, str]:
    """Lines the user marked wrong, for prompts."""
    return {area_id: str(value.get("text") or "") for area_id, value in (rejected or {}).items() if isinstance(value, dict)}


def proof_after_rejection(
    updates: dict[str, dict[str, Any]], rejected: dict[str, Any] | None
) -> dict[str, dict[str, Any]]:
    """For an area the user marked wrong, keep only proof sent after they did.

    Old messages already led to the wrong line, so they cannot bring it back. Proof without a send
    time cannot show it is newer and is dropped; an area left with no proof is not written.
    """
    kept: dict[str, dict[str, Any]] = {}
    for area_id, update in updates.items():
        record = (rejected or {}).get(area_id)
        rejected_at = _parse_time(record.get("at")) if isinstance(record, dict) else None
        if rejected_at is None:
            kept[area_id] = update
            continue
        old = {_evidence_key(item) for item in line_evidence(record)}
        evidence = [
            item
            for item in line_evidence(update)
            if _evidence_key(item) not in old
            and (sent_at := _parse_time(item.get("sent_at"))) is not None
            and sent_at > rejected_at
        ]
        if evidence:
            kept[area_id] = {"text": line_text(update), "evidence": evidence}
    return kept


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def merge_vibe(card: dict[str, Any] | None, updates: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """New text replaces the old line; evidence accumulates (most recent kept)."""
    merged: dict[str, dict[str, Any]] = {}
    for area_id in VIBE_AREA_IDS:
        current = (card or {}).get(area_id)
        update = updates.get(area_id)
        text = line_text(update) or line_text(current)
        if not text:
            continue
        evidence = line_evidence(current)
        for item in line_evidence(update):
            if all(_evidence_key(item) != _evidence_key(existing) for existing in evidence):
                evidence.append(item)
        merged[area_id] = {"text": text, "evidence": evidence[-MAX_VIBE_EVIDENCE:]}
    return merged


__all__ = [
    "BASIC_AREA_IDS",
    "CLEAR_DAY_COUNT",
    "DEEPER_AREA_IDS",
    "MAX_VIBE_LINE_CHARS",
    "VIBE_AREAS",
    "VIBE_AREA_GOALS",
    "VIBE_AREA_IDS",
    "VIBE_LINE_RULES",
    "VIBE_MILESTONES",
    "VIBE_MILESTONE_MEANINGS",
    "VibeProgress",
    "evidence_days",
    "line_evidence",
    "line_strength",
    "line_text",
    "merge_vibe",
    "proof_after_rejection",
    "rejected_texts",
    "validate_vibe_updates",
    "vibe_progress",
    "vibe_texts",
]
