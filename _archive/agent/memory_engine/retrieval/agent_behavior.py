from __future__ import annotations

from storage import list_agent_behavior_rules


def retrieve_agent_behavior_rules_for_context(user_id: str | None) -> list[dict[str, object]]:
    return list_agent_behavior_rules(user_id, limit=8)
