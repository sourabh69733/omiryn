"""How the user texts, from their own side of their newest uploaded chat."""

from __future__ import annotations

from typing import Any

from agent.context_engine.conversation_engine.personalization import texting_style_note
from storage.context_sources import list_whatsapp_imports, list_whatsapp_style_profiles

TEXTING_STYLE_SOURCE_TYPE = "texting_style"


def texting_style_sources(user_id: str | None) -> list[dict[str, Any]]:
    """How the user texts, from their own side of their newest uploaded chat, in every chat.

    A friend's style import is left out: that is someone else's way of texting.
    """
    if not user_id:
        return []
    for upload in list_whatsapp_imports(user_id=user_id):  # newest first
        if upload.get("style_kind") != "user_style" or not upload.get("selected_sender"):
            continue
        sender = str(upload["selected_sender"]).casefold()
        for profile in list_whatsapp_style_profiles(str(upload["id"]), user_id):
            note = texting_style_note(profile.get("summary") or {}) if str(profile.get("sender") or "").casefold() == sender else None
            if note:
                return [
                    {
                        "source_type": TEXTING_STYLE_SOURCE_TYPE,
                        "title": "How the user texts",
                        "content": note,
                        "metadata": {"import_id": upload["id"]},
                    }
                ]
        return []
    return []


__all__ = ["TEXTING_STYLE_SOURCE_TYPE", "texting_style_sources"]
