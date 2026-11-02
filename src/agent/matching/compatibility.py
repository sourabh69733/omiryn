"""How two users would get along, from their vibe cards.

Code decides what can be compared: areas where both have a line with proof. Private areas (values,
stories, deal breakers) are weighed only when both users allowed it, and even then never appear in a
reason, a difference or an icebreaker. A model writes the reasons; code keeps only reasons that
name a comparable, non-private area. The score is a code heuristic for shortlisting, not a verdict.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from agent.memory_engine.memories.ranking import text_relevance
from agent.shared.vibe import PRIVATE_AREA_IDS, VIBE_AREA_GOALS, VIBE_AREA_IDS, line_evidence, line_text

MIN_COMPARABLE_AREAS = 3
MAX_REASONS = 3
MAX_REASON_CHARS = 200

MATCH_REASONS_SYSTEM_PROMPT = """You judge whether two people would get along as friends, from notes about each.

Input JSON: {"a": {"name": ..., "areas": {area: line}}, "b": {...}, "comparable": [area ids both have],
"shareable": [area ids you may mention]}. Lines are plain descriptions written from what each person
said about themselves. Vibe means who they can accept in their life: humour, energy, interests, how
they keep in touch, what they are fine with in a friend. Not sameness: two different people can click.

Return JSON only:
{"fit": "yes" | "maybe" | "no",
 "reasons": [{"area": "<a shareable area id>", "text": "<one sentence, both names, specific>"}],
 "difference": {"area": "<a shareable area id>", "text": "<one difference they could live with, one sentence>"} | null,
 "icebreaker": "<one line one of them could open with, from a shareable area>" | null,
 "why_not": "<one sentence when fit is no>" | null}

Rules: at most three reasons, each from a different shareable area, each grounded in both lines.
Never use an area that is not in shareable, even if it is the real reason. No scores, no flattery,
no invented details. If the notes do not support a reason, say fit "maybe" with fewer reasons."""


@dataclass(frozen=True)
class MatchCheck:
    fit: str
    score: int
    comparable: tuple[str, ...]
    reasons: list[dict[str, str]] = field(default_factory=list)
    difference: dict[str, str] | None = None
    icebreaker: str | None = None
    why_not: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "fit": self.fit,
            "score": self.score,
            "comparable": list(self.comparable),
            "reasons": list(self.reasons),
            "difference": self.difference,
            "icebreaker": self.icebreaker,
            "why_not": self.why_not,
        }


def comparable_areas(areas_a: dict[str, Any], areas_b: dict[str, Any], *, both_private_allowed: bool) -> tuple[str, ...]:
    """Areas where both have a line with proof; private ones only with both consents."""
    return tuple(
        area_id
        for area_id in VIBE_AREA_IDS
        if (both_private_allowed or area_id not in PRIVATE_AREA_IDS)
        and line_text(areas_a.get(area_id)) and line_evidence(areas_a.get(area_id))
        and line_text(areas_b.get(area_id)) and line_evidence(areas_b.get(area_id))
    )


def shareable_areas(comparable: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(area_id for area_id in comparable if area_id not in PRIVATE_AREA_IDS)


def compatibility_score(areas_a: dict[str, Any], areas_b: dict[str, Any], comparable: tuple[str, ...]) -> int:
    """0 to 100: how much there is to compare, and how much the compared lines share. A shortlist
    number for an operator, nothing more; two different people can still click."""
    if not comparable:
        return 0
    coverage = len(comparable) / len(VIBE_AREA_IDS)
    overlap = sum(text_relevance(line_text(areas_a[a]), line_text(areas_b[a])) for a in comparable) / len(comparable)
    return round(100 * (0.6 * coverage + 0.4 * min(1.0, overlap * 4)))


def validate_match_reasons(raw: Any, shareable: tuple[str, ...]) -> dict[str, Any]:
    """Keep only what the cards support: reasons and the difference must name a shareable area,
    one reason per area, short texts. Anything else the model wrote is dropped."""
    data = raw if isinstance(raw, dict) else {}
    fit = str(data.get("fit") or "maybe").lower()
    if fit not in {"yes", "maybe", "no"}:
        fit = "maybe"
    seen: set[str] = set()
    reasons: list[dict[str, str]] = []
    for item in data.get("reasons") or []:
        if not isinstance(item, dict):
            continue
        area, text = str(item.get("area") or ""), " ".join(str(item.get("text") or "").split())
        if area in shareable and area not in seen and text:
            seen.add(area)
            reasons.append({"area": area, "text": text[:MAX_REASON_CHARS]})
        if len(reasons) == MAX_REASONS:
            break
    difference = data.get("difference")
    if not (isinstance(difference, dict) and str(difference.get("area") or "") in shareable and str(difference.get("text") or "").strip()):
        difference = None
    else:
        difference = {"area": str(difference["area"]), "text": " ".join(str(difference["text"]).split())[:MAX_REASON_CHARS]}
    icebreaker = data.get("icebreaker")
    icebreaker = " ".join(str(icebreaker).split())[:MAX_REASON_CHARS] if isinstance(icebreaker, str) and icebreaker.strip() else None
    why_not = data.get("why_not")
    why_not = " ".join(str(why_not).split())[:MAX_REASON_CHARS] if isinstance(why_not, str) and why_not.strip() else None
    if fit == "yes" and not reasons:
        fit = "maybe"
    return {"fit": fit, "reasons": reasons, "difference": difference, "icebreaker": icebreaker, "why_not": why_not}


def match_reasons_input(name_a: str, areas_a: dict[str, Any], name_b: str, areas_b: dict[str, Any], comparable: tuple[str, ...]) -> str:
    def lines(areas: dict[str, Any]) -> dict[str, str]:
        return {area_id: line_text(areas[area_id]) for area_id in comparable}

    return json.dumps(
        {
            "a": {"name": name_a, "areas": lines(areas_a)},
            "b": {"name": name_b, "areas": lines(areas_b)},
            "comparable": list(comparable),
            "shareable": list(shareable_areas(comparable)),
            "area_meaning": {area_id: VIBE_AREA_GOALS[area_id] for area_id in comparable},
        },
        ensure_ascii=False,
    )


async def check_compatibility(user_a: str, user_b: str, *, model: str | None = None) -> MatchCheck:
    """Load both cards, compare what can be compared, and ask the model for reasons when there is
    enough. With too little in common to judge, fit is "unknown" and no model call is made."""
    from agent.providers import write_match_reasons
    from storage import get_user_profile, get_vibe_card, private_matching_allowed

    card_a, card_b = get_vibe_card(user_a), get_vibe_card(user_b)
    both_private = private_matching_allowed(card_a) and private_matching_allowed(card_b)
    comparable = comparable_areas(card_a["areas"], card_b["areas"], both_private_allowed=both_private)
    score = compatibility_score(card_a["areas"], card_b["areas"], comparable)
    if len(comparable) < MIN_COMPARABLE_AREAS:
        return MatchCheck("unknown", score, comparable, why_not=f"only {len(comparable)} areas to compare; needs {MIN_COMPARABLE_AREAS}")
    name_a = str((get_user_profile(user_a) or {}).get("display_name") or "A").split()[0]
    name_b = str((get_user_profile(user_b) or {}).get("display_name") or "B").split()[0]
    raw = await write_match_reasons(
        match_reasons_input(name_a, card_a["areas"], name_b, card_b["areas"], comparable),
        conversation_id=f"match:{user_a}:{user_b}",
        model=model,
    )
    checked = validate_match_reasons(raw, shareable_areas(comparable))
    return MatchCheck(checked["fit"], score, comparable, checked["reasons"], checked["difference"], checked["icebreaker"], checked["why_not"])


__all__ = [
    "MATCH_REASONS_SYSTEM_PROMPT",
    "MIN_COMPARABLE_AREAS",
    "MatchCheck",
    "check_compatibility",
    "comparable_areas",
    "compatibility_score",
    "match_reasons_input",
    "shareable_areas",
    "validate_match_reasons",
]
