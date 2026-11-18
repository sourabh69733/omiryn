"""Match notes: who a person is, written from their own messages, for finding people they would
enjoy talking to.

The vibe card holds one line for each of eleven fixed areas and counts a line as clear only after
two days of proof, so it fills slowly and says little. Memory keeps what happened, which in a
playful chat is mostly the story of the joke. Neither gives the match judge what it needs. Match
notes are an open list: several short notes per kind, each backed by the person's own messages.

A model writes them (one call, only when there are new messages); code decides what it reads and
keeps only notes with a known kind and real messages behind them. A rebuild shows the model the
notes so far and the messages since, so old notes stay unless the new messages change them. Notes
are never shown to anyone: the judge (agent.matching.choose) reads them, and a reason told to
another person may be written only from the kinds in REASON_KINDS.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agent.shared.clock import utc_now
from agent.shared.timeline import message_time

logger = logging.getLogger(__name__)

NOTES_VERSION = 1
# kind -> what it means. The meaning goes to the model; it is not a question to ask anyone.
NOTE_KINDS: dict[str, str] = {
    "loves": "what they do or could talk about for an hour",
    "humour": "what makes them laugh and how they joke",
    "wants": "what they want from a friend, or from people right now",
    "gives": "what they are like to the people around them",
    "cannot_stand": "what they cannot stand in people",
    "rhythm": "their hours, how and how often they keep in touch, planned or spontaneous, a crowd or a few",
    "views": "opinions and beliefs they hold: work, money, god, politics, how to live",
    "moment": "what is going on in their life now",
}
# Kinds a reason told to another person may be written from. The rest are for the judge alone:
# beliefs and deal-breakers follow the vibe card's private areas, and what is going on in someone's
# life is theirs to tell.
REASON_KINDS = frozenset({"loves", "humour", "wants", "gives", "rhythm"})
# Kinds the judge reads only when the person allowed private matching (storage.private_matching_allowed).
PRIVATE_KINDS = frozenset({"views", "cannot_stand"})
# Kinds that say who someone is to talk to; readiness counts these.
CORE_KINDS = ("loves", "humour", "wants", "gives", "rhythm")

MAX_NOTES = 24
MAX_PER_KIND = 5
MAX_NOTE_CHARS = 220
MAX_EVIDENCE = 6
# What one call reads of the person's messages. More than that is read in several calls, oldest
# first, each folding into the notes; a long history is cut to its newest MAX_CALLS parts.
MAX_INPUT_CHARS = 12000
MAX_CALLS = 4
MAX_MESSAGE_CHARS = 400
# Fewer new messages than this since the last build and a rebuild is not worth a call.
MIN_NEW_MESSAGES = 8
# Enough to look for someone: this many notes, over this many of the core kinds. Six notes a
# person was where the judge still found the planted friend 15 times in 18 (design section 10.4).
READY_NOTES = 6
READY_CORE_KINDS = 3

MATCH_NOTES_SYSTEM_PROMPT = """You read what one person wrote and note who they are, so their companion app can find people they would enjoy talking to.

Input JSON: {"name", "today", "source", "current_notes": [{"id", "kind", "text"}], "messages": [{"n", "day", "text"}]}.
"messages" are only their own messages, oldest first. "current_notes" is what was noted before.
"source" says where the messages are from. "companion": what they wrote to the companion app since the current notes. "friend_chat": their own side of a chat with someone they know, which they shared; the other person's lines are not shown, so a line may answer something you cannot see. Note only what their own line shows, and never guess what the other person said or who they are.

People joke, exaggerate and play running games with a companion. Never record the events of a joke or a made-up story as facts about them. Read through the jokes to what they show about the person: the kind of humour, what they keep coming back to, when they are awake, what they do and eat and watch, how they treat people, how they write.

Return JSON only: {"notes": [{"kind": "<kind>", "text": "<one plain English sentence about them, specific>", "from": [<message numbers>], "keeps": "<id of the current note this keeps or rewrites>" | null}]}

Kinds:
KINDS

Return the whole list as it should now stand. Keep a current note that is still true by repeating it with "keeps" set to its id; rewrite it the same way when the new messages add to it or correct it; leave it out when the person says it is over or wrong. Add new notes from the new messages.

Rules: only what they said or plainly showed about themselves, never from one stray word. Plain English even when they write Hindi or Hinglish. Describe, do not quote. A new note names the messages it comes from. No health, mental health, sexual or financial details, even when they shared them. Do not write a note that would be true of almost anyone. At most MAX_PER_KIND notes of a kind and MAX_NOTES in all; leave out a kind with nothing to say."""
MATCH_NOTES_SYSTEM_PROMPT = (
    MATCH_NOTES_SYSTEM_PROMPT.replace("KINDS", "\n".join(f"- {kind}: {meaning}" for kind, meaning in NOTE_KINDS.items()))
    .replace("MAX_PER_KIND", str(MAX_PER_KIND))
    .replace("MAX_NOTES", str(MAX_NOTES))
)


def own_messages(conversations: list[dict[str, Any]], *, after: str | None = None, uploads: bool = False) -> list[dict[str, Any]]:
    """The user's own messages across their chats with Omi, oldest first, each with where it is
    (conversation and index) and when. Temporary chats are left out, as everywhere. A shared chat
    (an upload) is left out too unless `uploads` is set: its lines carry their old dates, so it is
    read once on its own (add_upload_to_notes), not by date with the rest."""
    out: list[dict[str, Any]] = []
    for conversation in conversations:
        if conversation.get("temporary") or (bool(conversation.get("import_source_id")) != uploads):
            continue
        for index, message in enumerate(conversation.get("messages") or []):
            text = " ".join(str(message.get("content") or "").split())
            if message.get("role") != "user" or not text:
                continue
            at = message_time(message)
            sent_at = at.isoformat() if at else None
            if after and (not sent_at or sent_at <= after):
                continue
            out.append({"conversation_id": str(conversation["id"]), "message_index": index, "sent_at": sent_at, "text": text[:MAX_MESSAGE_CHARS]})
    out.sort(key=lambda item: item["sent_at"] or "")
    return out


def message_parts(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """The messages cut into parts one call can read, oldest first; only the newest MAX_CALLS parts."""
    parts: list[list[dict[str, Any]]] = [[]]
    size = 0
    for message in messages:
        if parts[-1] and size + len(message["text"]) > MAX_INPUT_CHARS:
            parts.append([])
            size = 0
        parts[-1].append(message)
        size += len(message["text"])
    return [part for part in parts if part][-MAX_CALLS:]


def notes_input(name: str, today: str, current: list[dict[str, Any]], messages: list[dict[str, Any]], source: str = "companion") -> tuple[str, dict[int, dict[str, Any]]]:
    """The JSON the model reads for one part, and what each message number stands for."""
    numbered = {n: message for n, message in enumerate(messages, start=1)}
    payload = {
        "name": name,
        "today": today,
        "source": source,
        "current_notes": [{"id": note["id"], "kind": note["kind"], "text": note["text"]} for note in current],
        "messages": [{"n": n, "day": (message["sent_at"] or "")[:10], "text": message["text"]} for n, message in numbered.items()],
    }
    return json.dumps(payload, ensure_ascii=False), numbered


def validate_notes(raw: Any, current: list[dict[str, Any]], numbered: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep a note only with a known kind, a sentence, and proof: messages the model was shown, or
    the proof of the current note it keeps. Proof adds up when a kept note cites new messages too.
    Bounded per kind and in all; ids are kept for kept notes and made for new ones."""
    by_id = {note["id"]: note for note in current}
    taken_ids = set(by_id)
    out: list[dict[str, Any]] = []
    seen_text: set[str] = set()
    per_kind: dict[str, int] = {}
    used_keeps: set[str] = set()
    for item in (raw.get("notes") if isinstance(raw, dict) else None) or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        text = _whole(" ".join(str(item.get("text") or "").split()))
        if kind not in NOTE_KINDS or not text or text.casefold() in seen_text or per_kind.get(kind, 0) >= MAX_PER_KIND:
            continue
        keeps = item.get("keeps") if isinstance(item.get("keeps"), str) and item.get("keeps") in by_id and item.get("keeps") not in used_keeps else None
        evidence = list(by_id[keeps].get("evidence") or []) if keeps else []
        known = {(e["conversation_id"], e["message_index"]) for e in evidence}
        for number in item.get("from") or []:
            message = numbered.get(number) if isinstance(number, int) and not isinstance(number, bool) else None
            if message and (message["conversation_id"], message["message_index"]) not in known:
                known.add((message["conversation_id"], message["message_index"]))
                evidence.append({key: message[key] for key in ("conversation_id", "message_index", "sent_at") if message.get(key) is not None})
        if not evidence:
            continue
        if keeps:
            used_keeps.add(keeps)
            note_id = keeps
        else:
            note_id = _new_id(taken_ids)
            taken_ids.add(note_id)
        seen_text.add(text.casefold())
        per_kind[kind] = per_kind.get(kind, 0) + 1
        # Newest proof is kept when there is more than fits.
        out.append({"id": note_id, "kind": kind, "text": text, "evidence": evidence[-MAX_EVIDENCE:]})
        if len(out) == MAX_NOTES:
            break
    return out


def notes_readiness(notes: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Whether there is enough to look for someone, from the notes alone: how many, and how many of
    the kinds that say who a person is to talk to."""
    notes = notes or []
    have = tuple(kind for kind in NOTE_KINDS if any(note.get("kind") == kind for note in notes))
    core = tuple(kind for kind in CORE_KINDS if kind in have)
    return {
        "ready": len(notes) >= READY_NOTES and len(core) >= READY_CORE_KINDS,
        "notes": len(notes),
        "kinds": have,
        "missing_core": tuple(kind for kind in CORE_KINDS if kind not in have),
        "needs": {"notes": READY_NOTES, "core_kinds": READY_CORE_KINDS},
    }


def match_notes_readiness(user_id: str) -> dict[str, Any]:
    from storage import get_match_notes

    stored = get_match_notes(user_id)
    return notes_readiness(stored["notes"] if stored else [])


def rebuild_due(user_id: str) -> bool:
    """There are enough new messages since the last build (or no build yet and enough to read)."""
    from storage import get_match_notes, list_conversations

    stored = get_match_notes(user_id)
    return len(own_messages(list_conversations(user_id), after=(stored or {}).get("covered_upto"))) >= MIN_NEW_MESSAGES


async def rebuild_match_notes(user_id: str, *, force: bool = False, model: str | None = None) -> dict[str, Any]:
    """Read the messages since the last build and write the notes as they should now stand."""
    from storage import get_match_notes, list_conversations, set_match_notes

    stored = get_match_notes(user_id) or {"notes": [], "covered_upto": None, "messages_seen": 0}
    current = _current(stored)
    messages = own_messages(list_conversations(user_id), after=stored.get("covered_upto"))
    if not messages or (len(messages) < MIN_NEW_MESSAGES and not force):
        return {"status": "nothing_new", "notes": len(current), "new_messages": len(messages)}
    notes = await _fold(user_id, current, messages, "companion", model)
    if notes is None:
        return {"status": "kept", "notes": len(current), "new_messages": len(messages)}
    if not notes:
        return {"status": "nothing_found", "notes": 0, "new_messages": len(messages)}
    covered = max((message["sent_at"] for message in messages if message.get("sent_at")), default=stored.get("covered_upto"))
    set_match_notes(user_id, {**stored, "version": NOTES_VERSION, "notes": notes, "covered_upto": covered, "messages_seen": int(stored.get("messages_seen") or 0) + len(messages)})
    logger.info("agent.match_notes.rebuilt user_id=%s notes=%s new_messages=%s", user_id, len(notes), len(messages))
    return {"status": "rebuilt", "notes": len(notes), "new_messages": len(messages), "ready": notes_readiness(notes)["ready"]}


async def add_upload_to_notes(user_id: str, source_id: str, *, model: str | None = None) -> dict[str, Any]:
    """Read the person's own side of a chat they shared into their notes, once. This is how Omi
    knows someone after one upload instead of after weeks: a real chat with a friend shows their
    humour, what they love and how they keep in touch far faster than first chats with Omi do.
    The proof points at the stored upload, so deleting the upload takes the proof with it."""
    from storage import get_match_notes, set_match_notes
    from storage.conversations import import_conversation

    stored = get_match_notes(user_id) or {"notes": [], "covered_upto": None, "messages_seen": 0}
    done = list(stored.get("uploads") or [])
    if source_id in done:
        return {"status": "already_read", "notes": len(_current(stored))}
    conversation = import_conversation(user_id, source_id)
    messages = own_messages([conversation], uploads=True) if conversation else []
    if len(messages) < MIN_NEW_MESSAGES:
        return {"status": "nothing_new", "notes": len(_current(stored)), "new_messages": len(messages)}
    current = _current(stored)
    notes = await _fold(user_id, current, messages, "friend_chat", model)
    if notes is None:
        return {"status": "kept", "notes": len(current), "new_messages": len(messages)}
    # Read again by now? Another writer may have saved meanwhile; take the newest stored state for the rest.
    latest = get_match_notes(user_id) or stored
    set_match_notes(user_id, {**latest, "version": NOTES_VERSION, "notes": notes or current, "uploads": sorted({*(latest.get("uploads") or []), source_id}), "messages_seen": int(latest.get("messages_seen") or 0) + len(messages)})
    logger.info("agent.match_notes.upload_read user_id=%s notes=%s lines=%s", user_id, len(notes or current), len(messages))
    return {"status": "rebuilt" if notes else "nothing_found", "notes": len(notes or current), "new_messages": len(messages), "ready": notes_readiness(notes or current)["ready"]}


def _current(stored: dict[str, Any]) -> list[dict[str, Any]]:
    return [note for note in stored["notes"] if isinstance(note, dict) and note.get("id") and note.get("kind") in NOTE_KINDS]


async def _fold(user_id: str, current: list[dict[str, Any]], messages: list[dict[str, Any]], source: str, model: str | None) -> list[dict[str, Any]] | None:
    """Read the messages in parts, each folding into the notes. None when an answer was empty or
    broken while there were notes: nothing is to be saved, so the same messages are read again."""
    from agent.providers import write_match_notes
    from storage import get_user_profile

    name = str((get_user_profile(user_id) or {}).get("display_name") or "They").split()[0]
    today = utc_now().date().isoformat()
    notes = current
    for part in message_parts(messages):
        text, numbered = notes_input(name, today, notes, part, source)
        written = validate_notes(await write_match_notes(text, model=model), notes, numbered)
        if not written and notes:
            logger.warning("agent.match_notes.empty_answer user_id=%s kept=%s", user_id, len(current))
            return None
        notes = written
    return notes


async def refresh_match_notes(user_id: str) -> dict[str, Any]:
    """The daily pass (with the user card rebuild): only for people who are in a match group, and
    only when there are enough new messages to be worth a call."""
    from storage import match_pools_for_user

    if not match_pools_for_user(user_id):
        return {"status": "not_matching"}
    if not rebuild_due(user_id):
        return {"status": "nothing_new"}
    return await rebuild_match_notes(user_id)


def _whole(text: str) -> str:
    """A note that runs long ends at a whole word, never in the middle of one."""
    if len(text) <= MAX_NOTE_CHARS:
        return text
    cut = text[:MAX_NOTE_CHARS]
    return cut[: cut.rfind(" ")].rstrip(",;:") + "…" if " " in cut else cut


def _new_id(taken: set[str]) -> str:
    n = len(taken) + 1
    while f"n{n}" in taken:
        n += 1
    return f"n{n}"


__all__ = [
    "CORE_KINDS",
    "MATCH_NOTES_SYSTEM_PROMPT",
    "MIN_NEW_MESSAGES",
    "NOTES_VERSION",
    "NOTE_KINDS",
    "PRIVATE_KINDS",
    "REASON_KINDS",
    "add_upload_to_notes",
    "match_notes_readiness",
    "message_parts",
    "notes_input",
    "notes_readiness",
    "own_messages",
    "rebuild_due",
    "rebuild_match_notes",
    "refresh_match_notes",
    "validate_notes",
]
