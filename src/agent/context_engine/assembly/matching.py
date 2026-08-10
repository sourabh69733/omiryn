"""Projects approved matching memory into soft breadth and depth progress."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from agent.context_engine.contracts.models import MatchingDimensionProgress, MatchingUnderstanding
from storage import list_profile_facts


FOUNDATION_DIMENSIONS = (
    "relationship_intent",
    "desired_partner",
    "age_preference",
    "location_preference",
    "desired_personality",
)

DEEPER_DIMENSIONS = (
    "values",
    "lifestyle",
    "family_expectations",
    "communication",
    "attraction",
    "boundaries",
    "relationship_dynamics",
    "flexibility",
)

MATCHING_DIMENSIONS = FOUNDATION_DIMENSIONS + DEEPER_DIMENSIONS

# These are internal, language-neutral data-point identities. We deliberately do not
# infer progress by searching user messages or model-written labels for keywords.
_DIMENSION_IDENTITIES = {
    "relationship_intent": {
        "relationship_intent",
        "dating_intent",
        "relationship_goal",
        "relationship_goals",
    },
    "desired_partner": {
        "desired_partner",
        "partner_identity",
        "gender_preference",
        "interested_in",
        "partner_preference",
    },
    "age_preference": {
        "age_preference",
        "partner_age",
        "preferred_age",
        "preferred_age_range",
    },
    "location_preference": {
        "location_preference",
        "partner_location",
        "preferred_location",
        "preferred_city",
        "distance_preference",
        "relocation_preference",
    },
    "desired_personality": {
        "desired_personality",
        "partner_personality",
        "partner_qualities",
        "personality_preference",
        "preferred_traits",
    },
    "values": {"values", "core_values", "partner_values", "value_preference"},
    "lifestyle": {"lifestyle", "partner_lifestyle", "lifestyle_preference", "daily_life"},
    "family_expectations": {
        "family_expectations",
        "family_plans",
        "children_preference",
        "family_involvement",
        "religion_preference",
        "culture_preference",
    },
    "communication": {
        "communication",
        "communication_style",
        "communication_preference",
        "conflict_style",
    },
    "attraction": {
        "attraction",
        "physical_preference",
        "appearance_preference",
        "chemistry_preference",
    },
    "boundaries": {"boundaries", "dealbreakers", "non_negotiables", "hard_preference"},
    "relationship_dynamics": {
        "relationship_dynamics",
        "affection_preference",
        "emotional_needs",
        "relationship_needs",
    },
    "flexibility": {
        "flexibility",
        "preference_flexibility",
        "tradeoffs",
        "nice_to_have",
    },
}

_DEPTH_SCORE = {"unknown": 0, "mentioned": 1, "clear": 2, "deep": 3}


def build_matching_understanding(
    *,
    user_id: str | None,
    user_profile: dict[str, Any] | None = None,
) -> MatchingUnderstanding:
    facts = (
        list_profile_facts(user_id, statuses={"active"}, used_for_matching=True)
        if user_id
        else []
    )
    return calculate_matching_understanding(facts, user_profile=user_profile)


def calculate_matching_understanding(
    facts: list[dict[str, Any]],
    *,
    user_profile: dict[str, Any] | None = None,
) -> MatchingUnderstanding:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        if fact.get("status") != "active" or not fact.get("used_for_matching", False):
            continue
        dimension = _fact_dimension(fact)
        if dimension:
            grouped[dimension].append(fact)

    interested_in = str((user_profile or {}).get("interested_in") or "").strip()
    if interested_in and interested_in.casefold() not in {"unknown", "unspecified"}:
        grouped["desired_partner"].append(
            {
                "confidence": 1.0,
                "confidence_state": "confirmed",
                "evidence": [],
                "source_kind": "user_profile",
            }
        )

    dimensions = tuple(
        _dimension_progress(dimension_id, grouped.get(dimension_id, []))
        for dimension_id in MATCHING_DIMENSIONS
    )
    by_id = {dimension.id: dimension for dimension in dimensions}
    known = tuple(item.id for item in dimensions if item.depth != "unknown")
    unexplored = tuple(item.id for item in dimensions if item.depth == "unknown")
    can_deepen = tuple(item.id for item in dimensions if item.depth in {"mentioned", "clear"})
    foundation_covered = sum(
        by_id[dimension_id].depth != "unknown" for dimension_id in FOUNDATION_DIMENSIONS
    )
    deeper_covered = sum(
        by_id[dimension_id].depth != "unknown" for dimension_id in DEEPER_DIMENSIONS
    )
    breadth_percent = round((len(known) / len(MATCHING_DIMENSIONS)) * 100)
    depth_percent = _known_depth_percent(dimensions)

    if foundation_covered == len(FOUNDATION_DIMENSIONS) and deeper_covered >= 6 and all(
        by_id[dimension_id].depth in {"clear", "deep"}
        for dimension_id in FOUNDATION_DIMENSIONS
    ):
        level = "deep"
    elif foundation_covered >= 4 and deeper_covered >= 3:
        level = "useful"
    elif foundation_covered >= 3:
        level = "basic"
    else:
        level = "starting"

    return MatchingUnderstanding(
        level=level,
        breadth_percent=breadth_percent,
        depth_percent=depth_percent,
        foundation_covered=foundation_covered,
        foundation_total=len(FOUNDATION_DIMENSIONS),
        dimensions=dimensions,
        known_dimensions=known,
        unexplored_dimensions=unexplored,
        can_deepen_dimensions=can_deepen,
    )


def _fact_dimension(fact: dict[str, Any]) -> str | None:
    identities = {
        _snake_key(str(fact.get("category") or "")),
        _snake_key(str(fact.get("key") or "")),
    }
    identities.discard("")
    for dimension_id in MATCHING_DIMENSIONS:
        if identities & _DIMENSION_IDENTITIES[dimension_id]:
            return dimension_id
    return None


def _dimension_progress(
    dimension_id: str,
    facts: list[dict[str, Any]],
) -> MatchingDimensionProgress:
    if not facts:
        return MatchingDimensionProgress(id=dimension_id)

    confidence = max((_confidence(fact.get("confidence")) for fact in facts), default=0.0)
    evidence_count = len(
        {
            _evidence_identity(evidence)
            for fact in facts
            for evidence in (fact.get("evidence") or [])
            if _evidence_identity(evidence)
        }
    )
    states = {str(fact.get("confidence_state") or "active").strip().lower() for fact in facts}
    if "confirmed" in states or (confidence >= 0.75 and evidence_count >= 2):
        depth = "deep"
    elif confidence >= 0.65 and "candidate" not in states:
        depth = "clear"
    else:
        depth = "mentioned"
    return MatchingDimensionProgress(
        id=dimension_id,
        depth=depth,
        fact_count=len(facts),
        evidence_count=evidence_count,
        confidence=round(confidence, 3),
    )


def _known_depth_percent(dimensions: tuple[MatchingDimensionProgress, ...]) -> int:
    known = [item for item in dimensions if item.depth != "unknown"]
    if not known:
        return 0
    score = sum(_DEPTH_SCORE[item.depth] for item in known)
    return round((score / (len(known) * _DEPTH_SCORE["deep"])) * 100)


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _evidence_identity(evidence: Any) -> str:
    if isinstance(evidence, dict):
        conversation_id = str(evidence.get("conversation_id") or "")
        message_index = str(evidence.get("message_index") or "")
        text = str(evidence.get("text") or evidence.get("quote") or "").strip().casefold()
        return "|".join((conversation_id, message_index, text))
    return str(evidence or "").strip().casefold()


def _snake_key(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")
