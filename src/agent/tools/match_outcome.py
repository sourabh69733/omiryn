"""record_match_outcome: the reply model records what the user said came of an introduction Omi made.

On only for a user with an introduction they have heard about. The model decides when the user has
told it something worth recording; code checks the pair is theirs and stores the outcome under the
user's name in the plan, and sets the pair's status, which the operator sees.
"""

from __future__ import annotations

from typing import Any

from agent.matching.hosting import CLOSED_STATUSES, OPEN_STATUSES
from agent.shared.clock import utc_now

from .registry import Tool, ToolContext, ToolResult, register_tool

OUTCOMES = ("met", "no_show", "declined", "still_talking")
NOTE_CHARS = 200

DESCRIPTION = (
    "Record what the user told you came of an introduction you made (see \"Introductions you made\"): "
    "\"met\" when they met the person, \"no_show\" when the meet did not happen, \"declined\" when they do "
    "not want to meet or to go on, \"still_talking\" when they met and are still in touch. Call it in the "
    "same turn they tell you, with the pair id from your notes, then reply as a friend would. Only what "
    "they said, never a guess."
)
PARAMETERS = {
    "type": "object",
    "properties": {
        "pair_id": {"type": "string", "description": "The pair id from \"Introductions you made\"."},
        "outcome": {"type": "string", "enum": list(OUTCOMES)},
        "note": {"type": "string", "description": "Their words on it, a few words at most, e.g. \"went well, same again next week\"."},
    },
    "required": ["pair_id", "outcome"],
}


def _has_open_introduction(context: ToolContext) -> bool:
    if not context.user_id:
        return False
    from storage import match_pairs_for_user

    for pair in match_pairs_for_user(context.user_id):
        told = ((pair.get("plan") or {}).get("told") or {}).get(context.user_id) or {}
        if pair["status"] in OPEN_STATUSES | CLOSED_STATUSES and told.get("sent"):
            return True
    return False


async def _run(arguments: dict[str, Any], context: ToolContext) -> ToolResult:
    from storage import get_match_pair, update_match_pair_plan

    pair_id = str(arguments.get("pair_id") or "").strip()
    outcome = str(arguments.get("outcome") or "").strip()
    note = " ".join(str(arguments.get("note") or "").split())[:NOTE_CHARS]
    if outcome not in OUTCOMES:
        return ToolResult(f"record_match_outcome takes one of {', '.join(OUTCOMES)}; nothing was recorded.", {"ok": False, "error": "bad_outcome"})
    pair = get_match_pair(pair_id) if pair_id else None
    if pair is None or context.user_id not in (pair["user_a"], pair["user_b"]):
        return ToolResult("That pair id is not one of this user's introductions; nothing was recorded.", {"ok": False, "error": "unknown_pair"})
    now = utc_now().isoformat()

    def record(plan: dict[str, Any]) -> dict[str, Any]:
        plan.setdefault("outcomes", []).append({"user_id": context.user_id, "outcome": outcome, "note": note or None, "at": now})
        return plan

    update_match_pair_plan(pair_id, record, status=outcome)
    return ToolResult(f"Recorded: {outcome}. Now answer the user as a friend would; do not mention recording anything.", {"outcome": outcome})


RECORD_MATCH_OUTCOME = register_tool(
    Tool(name="record_match_outcome", description=DESCRIPTION, parameters=PARAMETERS, run=_run, enabled=_has_open_introduction, timeout_seconds=4.0)
)

__all__ = ["OUTCOMES", "RECORD_MATCH_OUTCOME"]
