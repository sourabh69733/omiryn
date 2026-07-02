from __future__ import annotations

from typing import Any

from storage import list_profile_facts


def retrieve_profile_facts_for_context(user_id: str | None) -> list[dict[str, Any]]:
    if not user_id:
        return []
    return list_profile_facts(user_id, used_for_chat_context=True)
