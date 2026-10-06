"""Stores the user's friend vibe card and the milestone it has reached."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from agent.memory_engine.memories.vibe import line_evidence, line_text, merge_vibe, proof_after_rejection, vibe_progress
from agent.shared.clock import utc_now

from .database import ENGINE
from .schema import agent_vibe_cards
from .utils import _protect_text, _require_user_id, _unprotect_text

# Writers that lose a race re-read the card and merge again, this many times at most.
WRITE_ATTEMPTS = 5

# Stored next to the area lines: lines the user marked wrong, with when and the proof behind them.
REJECTED_KEY = "_rejected"
# The intro Omi wrote from the non-private lines: {"text", "chips", "source"} (source = the lines it used).
INTRO_KEY = "_intro"


def get_vibe_card(user_id: str) -> dict[str, Any]:
    """{"areas": {area_id: {"text", "evidence"}}, "rejected": {area_id: {"text", "evidence", "at"}},
    "intro": {"text", "chips", "source"} | None, "milestone": id, "milestone_reached_at": datetime | None}."""
    return _read(_require_user_id(user_id, "agent vibe card"))[0]


def _read(owner_id: str) -> tuple[dict[str, Any], str | None]:
    """The card, plus its stored text, which a write checks is unchanged before replacing it."""
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(agent_vibe_cards).where(agent_vibe_cards.c.user_id == owner_id)
        ).mappings().first()
    if not row:
        return {"areas": {}, "rejected": {}, "intro": None, "milestone": "starting", "milestone_reached_at": None}, None
    stored = _stored(owner_id, row["card"])
    intro = stored.get(INTRO_KEY)
    return {
        "areas": merge_vibe(stored, {}),
        "rejected": _rejected(stored),
        "intro": intro if isinstance(intro, dict) else None,
        "milestone": row["milestone"],
        "milestone_reached_at": row["milestone_reached_at"],
    }, row["card"]


def update_vibe_card(
    user_id: str,
    updates: dict[str, dict[str, Any]],
    *,
    reject: tuple[str, ...] = (),
    drop: tuple[str, ...] = (),
    replace_evidence: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Merge area lines; the milestone moves (up or down) only when the count crosses one.

    reject: areas the user marked wrong. The line goes, and that area takes a new line only with
    proof sent afterwards; a saved new line clears the mark. "applied" lists the areas written.
    drop: areas removed without marking them wrong (their proof is gone).
    replace_evidence: the updates' proof replaces the old proof (see merge_vibe).
    """
    owner_id = _require_user_id(user_id, "agent vibe card")
    for _ in range(WRITE_ATTEMPTS):
        current, version = _read(owner_id)
        written = _write(owner_id, current, version, updates, reject, drop, replace_evidence, now)
        if written is not None:
            return written
    raise RuntimeError("vibe card kept changing during the update")


def _write(
    owner_id: str,
    current: dict[str, Any],
    version: str | None,
    updates: dict[str, dict[str, Any]],
    reject: tuple[str, ...],
    drop: tuple[str, ...],
    replace_evidence: bool,
    now: datetime | None,
) -> dict[str, Any] | None:
    """Merge onto the card read as `version`; None when someone else wrote it first."""
    rejected = dict(current["rejected"])
    rejected_at = utc_now().isoformat()
    for area_id in reject:
        line = current["areas"].get(area_id)
        rejected[area_id] = {"text": line_text(line), "evidence": line_evidence(line), "at": rejected_at}
    updates = proof_after_rejection(updates, rejected)
    for area_id in updates:
        rejected.pop(area_id, None)
    areas = merge_vibe(
        {key: value for key, value in current["areas"].items() if key not in reject and key not in drop},
        updates,
        replace_evidence=replace_evidence,
    )
    milestone = vibe_progress(areas).milestone
    reached_at = (
        current["milestone_reached_at"]
        if milestone == current["milestone"] and current["milestone_reached_at"]
        else now or utc_now()
    )
    values = {
        "card": _card_text(owner_id, areas, rejected, current.get("intro")),
        "milestone": milestone,
        "milestone_reached_at": reached_at,
    }
    try:
        with ENGINE.begin() as connection:
            if version is None:
                connection.execute(agent_vibe_cards.insert().values(user_id=owner_id, **values))
            elif not connection.execute(
                agent_vibe_cards.update()
                .where(agent_vibe_cards.c.user_id == owner_id, agent_vibe_cards.c.card == version)
                .values(**values, updated_at=func.now())
            ).rowcount:
                return None
    except IntegrityError:
        return None
    return {
        "areas": areas,
        "rejected": rejected,
        "applied": tuple(updates),
        "milestone": milestone,
        "milestone_reached_at": reached_at,
    }


def drop_vibe_proof_from_conversation(user_id: str, conversation_id: str) -> dict[str, Any] | None:
    """A deleted chat takes its proof with it; a line left without proof goes too."""
    owner_id = _require_user_id(user_id, "agent vibe card")
    current = get_vibe_card(owner_id)
    touched = {
        area_id: {
            "text": line_text(line),
            "evidence": [item for item in line_evidence(line) if item["conversation_id"] != conversation_id],
        }
        for area_id, line in current["areas"].items()
        if any(item["conversation_id"] == conversation_id for item in line_evidence(line))
    }
    if not touched:
        return None
    keep = {area_id: line for area_id, line in touched.items() if line["evidence"]}
    return update_vibe_card(
        owner_id,
        keep,
        drop=tuple(area_id for area_id, line in touched.items() if not line["evidence"]),
        replace_evidence=True,
    )


def vibe_deletion_impact(user_id: str, conversation_id: str) -> dict[str, list[str]]:
    """Which vibe lines deleting this chat would remove, and which would only lose some proof."""
    removed: list[str] = []
    weakened: list[str] = []
    for area_id, line in get_vibe_card(user_id)["areas"].items():
        evidence = line_evidence(line)
        from_chat = [item for item in evidence if item["conversation_id"] == conversation_id]
        if not from_chat:
            continue
        (removed if len(from_chat) == len(evidence) else weakened).append(area_id)
    return {"removed": removed, "weakened": weakened}


def prune_vibe_proof_from_missing_chats(user_id: str, existing_conversation_ids: set[str]) -> bool:
    """Drop proof from chats that no longer exist (deleted before deletes cleaned the vibe)."""
    owner_id = _require_user_id(user_id, "agent vibe card")
    current = get_vibe_card(owner_id)
    missing = {
        item["conversation_id"]
        for line in current["areas"].values()
        for item in line_evidence(line)
        if item["conversation_id"] not in existing_conversation_ids
    }
    for conversation_id in missing:
        drop_vibe_proof_from_conversation(owner_id, conversation_id)
    return bool(missing)


def set_vibe_intro(user_id: str, intro: dict[str, Any]) -> None:
    """Save the intro; the lines and milestone stay as they are. Skipped if the card keeps changing."""
    owner_id = _require_user_id(user_id, "agent vibe card")
    for _ in range(WRITE_ATTEMPTS):
        current, version = _read(owner_id)
        card = _card_text(owner_id, current["areas"], current["rejected"], intro)
        try:
            with ENGINE.begin() as connection:
                if version is None:
                    connection.execute(
                        agent_vibe_cards.insert().values(
                            user_id=owner_id, card=card, milestone="starting", milestone_reached_at=utc_now()
                        )
                    )
                    return
                if connection.execute(
                    agent_vibe_cards.update()
                    .where(agent_vibe_cards.c.user_id == owner_id, agent_vibe_cards.c.card == version)
                    .values(card=card)
                ).rowcount:
                    return
        except IntegrityError:
            continue


def _card_text(
    owner_id: str,
    areas: dict[str, Any],
    rejected: dict[str, Any],
    intro: dict[str, Any] | None,
) -> str:
    extra = {**({REJECTED_KEY: rejected} if rejected else {}), **({INTRO_KEY: intro} if intro else {})}
    return _protect_text(owner_id, json.dumps({**areas, **extra}, ensure_ascii=False))


def _stored(owner_id: str, stored: str) -> dict[str, Any]:
    try:
        value = json.loads(_unprotect_text(owner_id, stored) or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _rejected(stored: dict[str, Any]) -> dict[str, dict[str, Any]]:
    value = stored.get(REJECTED_KEY)
    return {
        area_id: record
        for area_id, record in (value.items() if isinstance(value, dict) else ())
        if isinstance(record, dict) and isinstance(record.get("at"), str)
    }


__all__ = [
    "drop_vibe_proof_from_conversation",
    "get_vibe_card",
    "prune_vibe_proof_from_missing_chats",
    "set_vibe_intro",
    "update_vibe_card",
    "vibe_deletion_impact",
]
