"""Removes chat text left in older debug records; keeps the counts, IDs and labels they need.

New snapshots and trace steps no longer store text (see agent_runtime). Rows written before that,
and background debug rows past the keep window, still can. Free text (anything with a space) is
dropped; numbers, booleans and short ID-like labels stay, so diagnostics and memory rotation work.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from agent.shared.clock import utc_now
from security.encryption import decrypt_json, maybe_encrypt_json

from .agent_runtime import _snapshot_memory_pointers, _snapshot_metrics
from .database import ENGINE
from .schema import agent_context_snapshots, agent_trace_steps, data_point_extraction_debug

# Statuses, model names, step names, IDs, labels: no spaces, short.
_LABEL = re.compile(r"^[\w.:/@+-]{1,80}$")
# Background debug rows newer than this stay whole, for debugging a recent batch.
DEFAULT_KEEP_DAYS = 7


def scrub_text(value: Any) -> Any:
    """Keep numbers, booleans, None and short labels; drop free text, at any depth."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if _LABEL.match(value) else None
    if isinstance(value, list):
        return [item for item in (scrub_text(item) for item in value) if item is not None]
    if isinstance(value, dict):
        kept = {key: scrub_text(item) for key, item in value.items()}
        return {key: item for key, item in kept.items() if item is not None}
    return None


def scrub_debug_records(*, apply: bool, keep_days: int = DEFAULT_KEEP_DAYS) -> dict[str, int]:
    """Count (and with apply=True, rewrite) the rows whose stored JSON would change."""
    cutoff = utc_now() - timedelta(days=keep_days)
    changed = {"context_snapshots": 0, "trace_steps": 0, "background_debug": 0}
    with ENGINE.begin() as connection:
        for row in connection.execute(select(agent_context_snapshots)).mappings():
            user_id = row["user_id"]
            summary, context = _open(user_id, row["summary_json"]), _open(user_id, row["context_json"])
            new_summary, new_context = _snapshot_metrics(summary), _snapshot_memory_pointers(context)
            if (new_summary, new_context) != (summary, context):
                changed["context_snapshots"] += 1
                if apply:
                    connection.execute(
                        agent_context_snapshots.update()
                        .where(agent_context_snapshots.c.id == row["id"])
                        .values(
                            summary_json=maybe_encrypt_json(user_id, new_summary),
                            context_json=maybe_encrypt_json(user_id, new_context),
                        )
                    )
        for row in connection.execute(select(agent_trace_steps)).mappings():
            user_id = row["user_id"]
            metadata = _open(user_id, row["metadata_json"])
            scrubbed = scrub_text(metadata) or {}
            if scrubbed != metadata:
                changed["trace_steps"] += 1
                if apply:
                    connection.execute(
                        agent_trace_steps.update()
                        .where(agent_trace_steps.c.id == row["id"])
                        .values(metadata_json=maybe_encrypt_json(user_id, scrubbed))
                    )
        old_debug = select(data_point_extraction_debug).where(data_point_extraction_debug.c.created_at < cutoff)
        for row in connection.execute(old_debug).mappings():
            user_id = row["user_id"]
            candidate, review = _open(user_id, row["candidate_json"]), _open(user_id, row["review_json"])
            new_candidate, new_review = scrub_text(candidate) or {}, scrub_text(review) or {}
            if (new_candidate, new_review) != (candidate, review):
                changed["background_debug"] += 1
                if apply:
                    connection.execute(
                        data_point_extraction_debug.update()
                        .where(data_point_extraction_debug.c.id == row["id"])
                        .values(
                            candidate_json=maybe_encrypt_json(user_id, new_candidate),
                            review_json=maybe_encrypt_json(user_id, new_review),
                        )
                    )
    return changed


def _open(user_id: str, stored: Any) -> Any:
    return decrypt_json(user_id, stored) if stored is not None else {}


__all__ = ["DEFAULT_KEEP_DAYS", "scrub_debug_records", "scrub_text"]
