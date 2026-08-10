"""Data-point type taxonomy based on structured categories, never message keywords."""

from __future__ import annotations

import re
from typing import Any


PROFILE_FACT_CATEGORIES = {
    "age",
    "biographical",
    "date_of_birth",
    "education",
    "gender",
    "hometown",
    "identity",
    "language",
    "languages",
    "life_background",
    "location",
    "nationality",
    "occupation",
    "profession",
    "pronouns",
    "relationship_status",
    "sexual_orientation",
    "work",
}


def canonical_fact_type(value: Any, category: Any) -> str:
    """Return the storage taxonomy type without interpreting natural-language content."""
    requested = str(value or "").strip().lower()
    category_key = snake_key(str(category or ""))

    if requested in {"chat_context_fact", "style_fact"}:
        return requested
    if requested == "matching_fact":
        return "matching_fact"
    if requested == "profile_fact":
        return "profile_fact" if category_key in PROFILE_FACT_CATEGORIES else "matching_fact"
    if category_key.startswith("whatsapp_"):
        return "chat_context_fact"
    if category_key in PROFILE_FACT_CATEGORIES:
        return "profile_fact"
    return "matching_fact"


def canonical_turn_data_point_type(value: Any, category: Any) -> str:
    requested = str(value or "").strip().lower()
    if requested not in {"profile_fact", "matching_fact"}:
        return requested
    return canonical_fact_type(requested, category)


def snake_key(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")
