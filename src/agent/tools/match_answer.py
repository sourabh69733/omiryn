"""answer_match: the reply model records whether the user wants an introduction Omi offered.

On only for a user with an open ask (Omi told them about someone and they have not answered). The
model decides when the user has answered; code checks the pair is theirs and that the ask is still
open, then records the answer, which may queue the introduction or close the pair.
"""

from __future__ import annotations

from typing import Any

from agent.matching.asking import ANSWERS, open_ask_for, record_answer

from .registry import Tool, ToolContext, ToolResult, register_tool

DESCRIPTION = (
    "Record the user's answer to an introduction you offered (see \"Someone you offered to introduce\"): "
    "\"accept\" when they want you to introduce them, \"pass\" when they do not. Call it in the same turn "
    "they answer, with the pair id from your notes, then reply as a friend would. Only a clear answer, "
    "never a guess; a question about the person is not an answer."
)
PARAMETERS = {
    "type": "object",
    "properties": {
        "pair_id": {"type": "string", "description": "The pair id from \"Someone you offered to introduce\"."},
        "answer": {"type": "string", "enum": list(ANSWERS)},
        "note": {"type": "string", "description": "Their words on it, a few words at most."},
    },
    "required": ["pair_id", "answer"],
}


def _has_open_ask(context: ToolContext) -> bool:
    if not context.user_id:
        return False
    from storage import match_pairs_for_user

    return any(open_ask_for(context.user_id, pair) for pair in match_pairs_for_user(context.user_id))


async def _run(arguments: dict[str, Any], context: ToolContext) -> ToolResult:
    pair_id = str(arguments.get("pair_id") or "").strip()
    answer = str(arguments.get("answer") or "").strip()
    result = record_answer(pair_id, context.user_id or "", answer, str(arguments.get("note") or ""))
    if not result.get("ok"):
        notes = {
            "bad_answer": f"answer_match takes one of {', '.join(ANSWERS)}; nothing was recorded.",
            "unknown_pair": "That pair id is not an introduction offered to this user; nothing was recorded.",
            "not_open": "That offer is no longer open; nothing was recorded. Tell the user plainly if they ask.",
        }
        return ToolResult(notes.get(str(result.get("error")), "Nothing was recorded."), {"ok": False, "error": result.get("error")})
    if result["status"] == "introduced":
        note = "Recorded: yes, and the other person had already said yes. You will introduce them shortly in this chat; for now answer as a friend would and do not promise a time or place."
    elif answer == "accept":
        note = "Recorded: yes. The other person has not answered yet; say you will let them know, without pressure. Do not share anything more about them."
    else:
        note = "Recorded: no. Answer as a friend would, no questions about why, and do not mention recording anything."
    return ToolResult(note, {"answer": answer, "status": result["status"]})


ANSWER_MATCH = register_tool(
    Tool(name="answer_match", description=DESCRIPTION, parameters=PARAMETERS, run=_run, enabled=_has_open_ask, timeout_seconds=4.0)
)

__all__ = ["ANSWER_MATCH"]
