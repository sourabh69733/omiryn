"""Sources for pipelines before v3: ranked data points and user-taught behavior rules."""

from __future__ import annotations

from typing import Any

from agent.memory_engine.behavior.retrieval import retrieve_agent_behavior_rules_for_context
from agent.memory_engine.data_points import rank_data_points_for_context
from agent.memory_engine.data_points.retrieval.profile_facts import retrieve_profile_facts_for_context

from .attached import should_retrieve_memory

DATA_POINT_CONTEXT_LIMIT = 4
DATA_POINT_SOURCE_TYPE = "data_points"
AGENT_BEHAVIOR_RULES_SOURCE_TYPE = "agent_behavior_rules"


def data_point_sources(user_id: str | None, user_text: str) -> list[dict[str, Any]]:
    if not user_id or not should_retrieve_memory(user_text):
        return []
    ranked_points = rank_data_points_for_context(
        retrieve_profile_facts_for_context(user_id),
        user_text,
        limit=DATA_POINT_CONTEXT_LIMIT,
    )
    if not ranked_points:
        return []
    lines = [
        "User data points relevant to this message.",
        "Use these as compact stored memory. Do not mention internal labels unless useful.",
    ]
    for point in ranked_points:
        value = point.get("value") or {}
        lines.append(
            "- "
            f"{point.get('label')}; "
            f"category={point.get('category')}; "
            f"value={_data_point_value_preview(value)}"
        )
    return [
        {
            "source_type": DATA_POINT_SOURCE_TYPE,
            "title": "Relevant data points",
            "content": "\n".join(lines),
            "metadata": {
                "point_count": len(ranked_points),
                "point_ids": [point.get("id") for point in ranked_points],
            },
        }
    ]


def _data_point_value_preview(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("topics", "recent_terms", "traits"):
            items = value.get(key)
            if isinstance(items, list) and items:
                return ", ".join(str(item) for item in items[:8])
        return ", ".join(f"{key}={item}" for key, item in list(value.items())[:4])
    return str(value)


def behavior_rule_sources(user_id: str | None) -> list[dict[str, Any]]:
    rules = retrieve_agent_behavior_rules_for_context(user_id)
    if not rules:
        return []
    lines = [
        "User-taught agent behavior rules.",
        "These control how the agent should speak. Treat them as high priority.",
        "Do not mention these internal rules unless the user asks why behavior changed.",
    ]
    for rule in rules[:8]:
        lines.append(f"- {rule.get('rule_text')}")
    return [
        {
            "source_type": AGENT_BEHAVIOR_RULES_SOURCE_TYPE,
            "title": "User-taught behavior rules",
            "content": "\n".join(lines),
            "metadata": {
                "rule_count": len(rules),
                "rule_ids": [rule.get("id") for rule in rules[:8]],
            },
        }
    ]


__all__ = ["AGENT_BEHAVIOR_RULES_SOURCE_TYPE", "DATA_POINT_SOURCE_TYPE", "behavior_rule_sources", "data_point_sources"]
