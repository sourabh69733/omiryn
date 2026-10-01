"""Second check on new vibe lines: a separate model call keeps only the proof that really shows them."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from agent.memory_engine.memories.vibe import VIBE_AREA_GOALS, line_evidence, line_text
from agent.providers import analyze_vibe_verification

logger = logging.getLogger(__name__)

# The text of one cited user message, or None when it cannot be found.
QuoteLookup = Callable[[dict[str, Any]], "str | None"]
QUOTE_CHARS = 600


async def verify_vibe_updates(
    updates: dict[str, dict[str, Any]],
    quote_for: QuoteLookup,
    *,
    conversation_id: str,
    model: str | None = None,
    timeout_seconds: float | None = 90,
) -> dict[str, dict[str, Any]]:
    """The updates with only the proof the checker kept; lines left without proof are dropped.

    Raises when the check itself fails; callers then save nothing, since a missing line is better
    than an unproven one.
    """
    lines: list[dict[str, Any]] = []
    by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    for area_id, line in updates.items():
        messages = []
        for item in line_evidence(line):
            quote = quote_for(item)
            if not quote:
                continue
            message_id = f"e{len(by_id) + 1}"
            by_id[message_id] = (area_id, item)
            messages.append({"id": message_id, "text": quote[:QUOTE_CHARS]})
        if messages:
            lines.append(
                {
                    "area": area_id,
                    "meaning": VIBE_AREA_GOALS.get(area_id, ""),
                    "line": line_text(line),
                    "messages": messages,
                }
            )
    if not lines:
        return {}
    raw = await analyze_vibe_verification(
        json.dumps({"lines": lines}, ensure_ascii=False),
        conversation_id=conversation_id,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    verified: dict[str, dict[str, Any]] = {}
    for area_id, kept_ids in (raw if isinstance(raw, dict) else {}).items():
        if area_id not in updates or not isinstance(kept_ids, list):
            continue
        # Only ids this line was given count; the checker cannot move proof between lines.
        evidence = [
            by_id[message_id][1]
            for message_id in dict.fromkeys(kept_ids)
            if isinstance(message_id, str) and by_id.get(message_id, ("",))[0] == area_id
        ]
        if evidence:
            verified[area_id] = {"text": line_text(updates[area_id]), "evidence": evidence}
    dropped = sorted(set(updates) - set(verified))
    if dropped:
        logger.info("agent.vibe.verify dropped=%s kept=%s", ",".join(dropped), ",".join(sorted(verified)))
    return verified


__all__ = ["verify_vibe_updates"]
