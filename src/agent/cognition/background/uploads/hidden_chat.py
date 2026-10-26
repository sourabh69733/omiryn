"""Learning from an upload: it becomes a hidden chat that the normal background run reads.

Memories, vibe lines and the user card then come with proof pointing at the uploaded lines, and
deleting the upload deletes that chat, so everything learned only from it goes too.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from agent.shared.clock import utc_now, utc_now_iso
from agent.shared.timeline import user_zone
from ingestion.upload_chat import notes_upload_messages, whatsapp_upload_messages
from storage import get_user_timezone, save_conversation
from storage.context_sources import update_context_source_metadata

from agent.cognition.background.idle import request_flush_now


def learn_from_whatsapp_upload(user_id: str, source_id: str, export_text: str, user_sender: str | None) -> str:
    """Start learning from the user's side of a WhatsApp export; returns the hidden chat's ID."""
    messages = whatsapp_upload_messages(export_text, user_sender, user_zone(get_user_timezone(user_id)))
    return _start(user_id, source_id, messages)


def learn_from_notes_upload(user_id: str, source_id: str, text: str, now: datetime | None = None) -> str:
    """Start learning from notes the user wrote about themselves; returns the hidden chat's ID."""
    return _start(user_id, source_id, notes_upload_messages(text, now or utc_now()))


def _start(user_id: str, source_id: str, messages: list[dict[str, Any]]) -> str:
    conversation_id = str(uuid4())
    save_conversation(
        {"id": conversation_id, "status": "active", "import_source_id": source_id, "messages": messages},
        user_id,
    )
    # The app shows this until the reader starts (next worker pass, within seconds).
    update_context_source_metadata(source_id, user_id, {"reading": {"state": "queued", "updated_at": utc_now_iso()}})
    request_flush_now(conversation_id, user_id)
    return conversation_id


__all__ = ["learn_from_notes_upload", "learn_from_whatsapp_upload"]
