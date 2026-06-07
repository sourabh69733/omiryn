from __future__ import annotations

from dataclasses import dataclass, field

HARD_REJECTION_SCORE = 0.0
SERIOUS_INTENTS = {"long_term", "marriage"}


@dataclass(frozen=True)
class AgePreference:
    min: int | None = None
    max: int | None = None


@dataclass(frozen=True)
class Dealbreaker:
    type: str
    severity: str


@dataclass(frozen=True)
class MatchProfile:
    id: str
    age: int
    age_preference: AgePreference
    relationship_intent: str
    values: list[str] = field(default_factory=list)
    lifestyle: list[str] = field(default_factory=list)
    communication_style: str | None = None
    religion_importance: str | None = None
    family_involvement: str | None = None
    children_preference: str | None = None
    city: str | None = None
    open_to_relocation: bool = False
    dealbreakers: list[Dealbreaker] = field(default_factory=list)
    attributes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HardFilterResult:
    pass_: bool
    reason: str | None = None


@dataclass(frozen=True)
class MatchResult:
    score: float
    decision: str
    explanation: str
    breakdown: dict[str, float]


def score_match(user_a: MatchProfile, user_b: MatchProfile) -> MatchResult:
    hard_filter = evaluate_hard_filters(user_a, user_b)

    if not hard_filter.pass_:
        return MatchResult(
            score=HARD_REJECTION_SCORE,
            decision="reject",
            explanation=hard_filter.reason or "Hard filters failed.",
            breakdown={"hard_filters": 0.0},
        )

    breakdown = {
        "intent": _score_relationship_intent(
            user_a.relationship_intent,
            user_b.relationship_intent,
            20,
        ),
        "values": _score_overlap(user_a.values, user_b.values, 25),
        "lifestyle": _score_overlap(user_a.lifestyle, user_b.lifestyle, 15),
        "communication": _score_exact(
            user_a.communication_style,
            user_b.communication_style,
            15,
        ),
        "family": _score_family_expectations(user_a, user_b, 15),
        "location": _score_location(user_a, user_b, 10),
    }

    score = round(sum(breakdown.values()), 2)

    return MatchResult(
        score=score,
        decision=_decision_for_score(score),
        explanation=_explain_score(score, breakdown, user_a, user_b),
        breakdown=breakdown,
    )


def evaluate_hard_filters(user_a: MatchProfile, user_b: MatchProfile) -> HardFilterResult:
    if user_a.id == user_b.id:
        return HardFilterResult(False, "Users cannot be matched with themselves.")

    age_check_a = _is_age_in_preference(user_b.age, user_a.age_preference)
    age_check_b = _is_age_in_preference(user_a.age, user_b.age_preference)

    if not age_check_a or not age_check_b:
        return HardFilterResult(False, "Age preference does not match both users.")

    if _has_dealbreaker_conflict(user_a, user_b) or _has_dealbreaker_conflict(user_b, user_a):
        return HardFilterResult(False, "At least one hard dealbreaker is triggered.")

    if not _is_relationship_intent_compatible(
        user_a.relationship_intent,
        user_b.relationship_intent,
    ):
        return HardFilterResult(False, "Relationship intent is not compatible.")

    return HardFilterResult(True)


def _is_age_in_preference(age: int, preference: AgePreference) -> bool:
    if preference.min is not None and age < preference.min:
        return False
    if preference.max is not None and age > preference.max:
        return False
    return True


def _has_dealbreaker_conflict(user: MatchProfile, candidate: MatchProfile) -> bool:
    candidate_attributes = set(candidate.attributes)

    return any(
        dealbreaker.severity == "hard" and dealbreaker.type in candidate_attributes
        for dealbreaker in user.dealbreakers
    )


def _is_relationship_intent_compatible(intent_a: str, intent_b: str) -> bool:
    if not intent_a or not intent_b:
        return False
    if intent_a == intent_b:
        return True
    return intent_a in SERIOUS_INTENTS and intent_b in SERIOUS_INTENTS


def _score_exact(value_a: str | None, value_b: str | None, max_score: float) -> float:
    if not value_a or not value_b:
        return 0.0
    return max_score if value_a == value_b else 0.0


def _score_relationship_intent(intent_a: str, intent_b: str, max_score: float) -> float:
    if not intent_a or not intent_b:
        return 0.0
    if intent_a == intent_b:
        return max_score
    return max_score * 0.8 if _is_relationship_intent_compatible(intent_a, intent_b) else 0.0


def _score_overlap(list_a: list[str], list_b: list[str], max_score: float) -> float:
    if not list_a or not list_b:
        return 0.0

    overlap_count = len(set(list_a).intersection(list_b))
    denominator = max(len(set(list_a)), len(set(list_b)))
    return round((overlap_count / denominator) * max_score, 2)


def _score_family_expectations(user_a: MatchProfile, user_b: MatchProfile, max_score: float) -> float:
    fields = [
        "religion_importance",
        "family_involvement",
        "children_preference",
    ]
    matches = sum(
        1
        for field_name in fields
        if getattr(user_a, field_name) and getattr(user_a, field_name) == getattr(user_b, field_name)
    )
    return round((matches / len(fields)) * max_score, 2)


def _score_location(user_a: MatchProfile, user_b: MatchProfile, max_score: float) -> float:
    if not user_a.city or not user_b.city:
        return 0.0
    if user_a.city == user_b.city:
        return max_score
    if user_a.open_to_relocation or user_b.open_to_relocation:
        return max_score / 2
    return 0.0


def _decision_for_score(score: float) -> str:
    if score >= 70:
        return "strong_candidate"
    if score >= 50:
        return "possible_candidate"
    return "low_priority"


def _explain_score(
    score: float,
    breakdown: dict[str, float],
    user_a: MatchProfile,
    user_b: MatchProfile,
) -> str:
    strengths = [key for key, value in breakdown.items() if value > 0]
    friction = []

    if user_a.city != user_b.city:
        friction.append("location")
    if user_a.communication_style != user_b.communication_style:
        friction.append("communication style")
    if user_a.children_preference != user_b.children_preference:
        friction.append("children preference")

    strengths_text = (
        f"Strong areas: {', '.join(strengths)}."
        if strengths
        else "No strong compatibility signals found yet."
    )
    friction_text = (
        f"Possible friction: {', '.join(friction)}."
        if friction
        else "No major friction found in the current profile data."
    )

    return f"Compatibility score is {score}. {strengths_text} {friction_text}"
