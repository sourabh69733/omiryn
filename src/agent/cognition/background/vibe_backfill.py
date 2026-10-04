"""Writes a vibe card from a user's past chats, for users who chatted before vibe cards existed."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from agent.memory_engine.memories.vibe import (
    VIBE_AREAS,
    VIBE_AREA_IDS,
    line_evidence,
    line_text,
    merge_vibe,
    proof_after_rejection,
    rejected_texts,
    validate_vibe_updates,
    vibe_texts,
    vibe_progress,
    with_current_proof,
)
from agent.cognition.background.vibe_verify import stored_quote_lookup, verify_vibe_updates
from agent.providers import analyze_vibe_backfill
from storage import get_vibe_card, list_conversations, update_vibe_card

# Most recent chat text sent to the model; older text is dropped first.
TRANSCRIPT_CHAR_BUDGET = 24000
MESSAGE_CHAR_LIMIT = 600


async def backfill_user_vibe(
    user_id: str,
    *,
    apply: bool = False,
    force: bool = False,
    model: str | None = None,
    timeout_seconds: float | None = 180,
) -> dict[str, Any]:
    """{"status", "areas": {area: {"text", "evidence"}}, "milestone"}. Writes only with apply=True."""
    current = get_vibe_card(user_id)
    if current["areas"] and not force:
        return {"status": "has_card", "areas": {}, "milestone": current["milestone"]}
    conversations = list_conversations(user_id)
    transcript, last_sent_at, refs = chat_transcript(conversations)
    if not transcript:
        return {"status": "no_messages", "areas": {}, "milestone": current["milestone"]}
    raw = await analyze_vibe_backfill(
        json.dumps(
            {
                "vibe_areas": [{"id": area_id, "meaning": goal} for area_id, _, goal in VIBE_AREAS],
                "current_vibe": vibe_texts(current["areas"]),
                "rejected_vibe": rejected_texts(current.get("rejected")),
                "chats": transcript,
            },
            ensure_ascii=False,
        ),
        conversation_id=conversations[0]["id"],
        model=model,
        timeout_seconds=timeout_seconds,
    )
    updates = validate_vibe_updates(
        raw.get("vibe") if isinstance(raw, dict) else None,
        resolve_evidence=lambda ref: refs.get(ref) if isinstance(ref, str) else None,
        max_updates=len(VIBE_AREA_IDS),
    )
    if updates:
        messages = {row["id"]: row.get("messages") or [] for row in conversations}
        # A second call keeps only proof that really shows each line; a failed check writes nothing.
        # With --force a line may be rewritten; it is re-proven with its old proof too.
        updates = await verify_vibe_updates(
            with_current_proof(updates, current["areas"]),
            lambda item: _message_text(messages, item),
            conversation_id=conversations[0]["id"],
            timeout_seconds=timeout_seconds,
        )
        # Old chats already led to a line the user marked wrong; they cannot bring it back.
        updates = proof_after_rejection(updates, current.get("rejected"))
    milestone = vibe_progress(merge_vibe(current["areas"], updates, replace_evidence=True)).milestone
    if not updates:
        return {"status": "nothing_found", "areas": {}, "milestone": milestone}
    if apply:
        # Dated to the last chat, so an old milestone is not announced as news.
        update_vibe_card(user_id, updates, replace_evidence=True, now=last_sent_at)
    return {"status": "written" if apply else "would_write", "areas": updates, "milestone": milestone}


async def recheck_user_vibe(
    user_id: str,
    *,
    apply: bool = False,
    timeout_seconds: float | None = 180,
) -> dict[str, Any]:
    """Re-prove every line of an existing card: proof from deleted chats or that does not show
    the line is dropped, and a line left without proof goes. For cards written before lines were
    re-proven on every rewrite."""
    current = get_vibe_card(user_id)
    if not current["areas"]:
        return {"status": "no_card", "kept": {}, "dropped": [], "milestone": current["milestone"]}
    quote = stored_quote_lookup(user_id)
    readable = {
        area_id: {"text": line_text(line), "evidence": [item for item in line_evidence(line) if quote(item)]}
        for area_id, line in current["areas"].items()
    }
    to_check = {area_id: line for area_id, line in readable.items() if line["evidence"]}
    kept: dict[str, dict[str, Any]] = {}
    if to_check:
        # Usage is logged against a chat; any chat the proof comes from will do.
        some_chat = next(item["conversation_id"] for line in to_check.values() for item in line["evidence"])
        kept = await verify_vibe_updates(
            to_check, quote, conversation_id=some_chat, timeout_seconds=timeout_seconds
        )
    dropped = sorted(set(current["areas"]) - set(kept))
    changed = dropped or any(
        len(line_evidence(kept[area_id])) != len(line_evidence(current["areas"][area_id])) for area_id in kept
    )
    milestone = vibe_progress(kept).milestone
    if apply and changed:
        update_vibe_card(user_id, kept, drop=tuple(dropped), replace_evidence=True)
    return {
        "status": ("rechecked" if apply else "would_recheck") if changed else "unchanged",
        "kept": kept,
        "dropped": dropped,
        "milestone": milestone,
    }


def chat_transcript(
    conversations: list[dict[str, Any]],
) -> tuple[str, datetime | None, dict[str, dict[str, Any]]]:
    """Chats oldest first as "[m3] user: ..." / "companion: ..." lines, trimmed to the budget.

    Only user lines get an id; refs maps each id still in the text to its evidence item,
    so a vibe line can cite only user messages the model actually saw.
    """
    lines: list[tuple[str, str | None, dict[str, Any] | None]] = []
    has_user_text = False
    last_sent_at: datetime | None = None
    next_id = 1
    for conversation in sorted(conversations, key=lambda row: row.get("created_at") or ""):
        lines.append((f"--- chat {conversation['id'][:8]} ---", None, None))
        for index, message in enumerate(conversation.get("messages") or []):
            role = message.get("role")
            text = " ".join(str(message.get("content") or "").split())
            if role not in {"user", "assistant"} or not text or message.get("delivery_status") == "failed":
                continue
            if role == "user":
                has_user_text = True
                ref_id = f"m{next_id}"
                next_id += 1
                target = {"conversation_id": conversation["id"], "message_index": index}
                if isinstance(message.get("created_at"), str):
                    target["sent_at"] = message["created_at"]
                lines.append((f"[{ref_id}] user: {text[:MESSAGE_CHAR_LIMIT]}", ref_id, target))
            else:
                lines.append((f"companion: {text[:MESSAGE_CHAR_LIMIT]}", None, None))
            sent_at = _parse_time(message.get("created_at"))
            if sent_at and (last_sent_at is None or sent_at > last_sent_at):
                last_sent_at = sent_at
    if not has_user_text:
        return "", None, {}
    kept: list[tuple[str, str | None, dict[str, Any] | None]] = []
    used = 0
    for line in reversed(lines):
        used += len(line[0]) + 1
        if used > TRANSCRIPT_CHAR_BUDGET:
            break
        kept.append(line)
    kept.reverse()
    refs = {ref_id: target for _, ref_id, target in kept if ref_id and target}
    return "\n".join(text for text, _, _ in kept), last_sent_at, refs


def _message_text(messages: dict[str, list[dict[str, Any]]], item: dict[str, Any]) -> str | None:
    rows = messages.get(item["conversation_id"]) or []
    index = item["message_index"]
    if 0 <= index < len(rows) and rows[index].get("role") == "user":
        return str(rows[index].get("content") or "") or None
    return None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


__all__ = ["backfill_user_vibe", "chat_transcript", "recheck_user_vibe"]
