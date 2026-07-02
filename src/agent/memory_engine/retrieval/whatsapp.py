from __future__ import annotations

from typing import Any

from storage import (
    list_whatsapp_chunks,
    list_whatsapp_imports,
    list_whatsapp_people,
    list_whatsapp_style_profiles,
)


def retrieve_whatsapp_imports(user_id: str | None = None) -> list[dict[str, Any]]:
    return list_whatsapp_imports(user_id=user_id)


def retrieve_whatsapp_memory(import_id: str, user_id: str | None = None) -> dict[str, Any]:
    return {
        "chunks": list_whatsapp_chunks(import_id, user_id),
        "people": list_whatsapp_people(import_id, user_id),
        "style_profiles": list_whatsapp_style_profiles(import_id, user_id),
    }
