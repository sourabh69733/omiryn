"""How two users would get along, from everything code can put in front of a judge.

Code decides what can be compared: vibe areas where both have a line with proof (private areas
only when both users allowed it, and even then never in a reason), touchpoints between their
memories (agent.matching.touchpoints), plain lines on how each writes (agent.matching.style) and the
meet facts. One model call judges and writes; code keeps only reasons whose source is allowed and
whose words come from that source. The score is a code heuristic for shortlisting, not a verdict.

Judge v1 (MATCH_REASONS_SYSTEM_PROMPT, validate_match_reasons) read vibe lines alone; it stays for
the evaluation that compares the two. Judge v2 (MATCH_JUDGE_SYSTEM_PROMPT, validate_match_judgement)
reads the whole evidence pack and is what check_compatibility runs.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from typing import Any

from agent.memory_engine.memories.ranking import text_relevance
from agent.shared.vibe import PRIVATE_AREA_IDS, VIBE_AREA_GOALS, VIBE_AREA_IDS, line_evidence, line_text

MIN_COMPARABLE_AREAS = 3
MAX_REASONS = 3
MAX_REASON_CHARS = 200
JUDGE_VERSION = 2
FITS = {"yes", "maybe", "no"}
MEET_FIT_LEVELS = {"easy", "awkward", "unknown"}

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

MATCH_JUDGE_SYSTEM_PROMPT = """You judge whether two people would get along as friends, from an evidence pack about them.

Input JSON:
- "a" and "b": each {"name", "areas": {area id: line}}. Lines are plain descriptions written from what
  each person said about themselves.
- "comparable": area ids both have. "shareable": the area ids a reason may name. "area_meaning": what each area is.
- "touchpoints": [{"n", "a", "b", "reason_ok"}]: pairs of things they each said that are about the same
  subject, found by code. Read each as shared (both are like this), complementary (one needs what the
  other is), a clash (one cannot stand what the other does), or nothing. "[name]" stands for a name taken out.
- "style": plain lines on how each writes to the companion (language, hours, length, laughs, pace).
  Compatibility facts, not personality.
- "meet": what is known about where and when each could meet, food and budget.

Vibe means who they can accept in their life, not sameness: two different people can click.

Return JSON only:
{"fit": "yes" | "maybe" | "no",
 "reasons": [{"source": "area:<shareable area id>" | "touchpoint:<n with reason_ok true>", "text": "<one sentence, both names, specific>"}],
 "difference": {"source": "<same forms>", "text": "<one difference they could live with, one sentence>"} | null,
 "icebreaker": "<one line one of them could open with, from an allowed source>" | null,
 "why_not": "<one sentence when fit is no>" | null,
 "clash": {"source": "area:<any comparable area id>" | "touchpoint:<n>", "note": "<what one cannot stand that the other does, one sentence>"} | null,
 "meet_fit": {"level": "easy" | "awkward" | "unknown", "line": "<the one thing a first plan should respect, or why it is awkward>"},
 "chemistry": "<one sentence: would a conversation between them flow, and who would carry it>"}

Rules: at most three reasons, each from a different source, each grounded in what both said; the text
must use words from the source lines, not new facts. Never put a private area or a touchpoint with
reason_ok false in a reason, difference or icebreaker, even if it is the real reason; a clash may name
any source. No scores, no flattery, no invented details. If the pack does not support a reason, say fit
"maybe" with fewer reasons."""


@dataclass(frozen=True)
class MatchCheck:
    fit: str
    score: int
    comparable: tuple[str, ...]
    reasons: list[dict[str, str]] = field(default_factory=list)
    difference: dict[str, str] | None = None
    icebreaker: str | None = None
    why_not: str | None = None
    clash: dict[str, str] | None = None
    meet_fit: dict[str, str] | None = None
    chemistry: str | None = None
    touchpoints: list[dict[str, Any]] = field(default_factory=list)
    style_lines: list[str] = field(default_factory=list)
    version: int = JUDGE_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "fit": self.fit,
            "score": self.score,
            "comparable": list(self.comparable),
            "reasons": list(self.reasons),
            "difference": self.difference,
            "icebreaker": self.icebreaker,
            "why_not": self.why_not,
            "clash": self.clash,
            "meet_fit": self.meet_fit,
            "chemistry": self.chemistry,
            "touchpoints": list(self.touchpoints),
            "style_lines": list(self.style_lines),
            "version": self.version,
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
    """Judge v1 output: keep only what the cards support: reasons and the difference must name a
    shareable area, one reason per area, short texts. Anything else the model wrote is dropped."""
    data = raw if isinstance(raw, dict) else {}
    fit = str(data.get("fit") or "maybe").lower()
    if fit not in FITS:
        fit = "maybe"
    seen: set[str] = set()
    reasons: list[dict[str, str]] = []
    for item in data.get("reasons") or []:
        if not isinstance(item, dict):
            continue
        area, text = str(item.get("area") or ""), _clean(item.get("text"))
        if area in shareable and area not in seen and text:
            seen.add(area)
            reasons.append({"area": area, "text": text})
        if len(reasons) == MAX_REASONS:
            break
    difference = data.get("difference")
    if not (isinstance(difference, dict) and str(difference.get("area") or "") in shareable and _clean(difference.get("text"))):
        difference = None
    else:
        difference = {"area": str(difference["area"]), "text": _clean(difference["text"])}
    icebreaker = _clean(data.get("icebreaker")) or None
    why_not = _clean(data.get("why_not")) or None
    if fit == "yes" and not reasons:
        fit = "maybe"
    return {"fit": fit, "reasons": reasons, "difference": difference, "icebreaker": icebreaker, "why_not": why_not}


# ---- judge v2: the evidence pack and its checks ----


def evidence_pack(
    name_a: str,
    areas_a: dict[str, Any],
    name_b: str,
    areas_b: dict[str, Any],
    comparable: tuple[str, ...],
    *,
    touchpoints: list[dict[str, Any]] | None = None,
    style_lines: list[str] | None = None,
    meet_a: dict[str, str] | None = None,
    meet_b: dict[str, str] | None = None,
) -> str:
    """What the judge reads, as JSON. Touchpoints are numbered from 1 in the order given."""

    def lines(areas: dict[str, Any]) -> dict[str, str]:
        return {area_id: line_text(areas[area_id]) for area_id in comparable}

    return json.dumps(
        {
            "a": {"name": name_a, "areas": lines(areas_a)},
            "b": {"name": name_b, "areas": lines(areas_b)},
            "comparable": list(comparable),
            "shareable": list(shareable_areas(comparable)),
            "area_meaning": {area_id: VIBE_AREA_GOALS[area_id] for area_id in comparable},
            "touchpoints": [
                {"n": index, "a": point["a"], "b": point["b"], "reason_ok": bool(point.get("reason_ok"))}
                for index, point in enumerate(touchpoints or [], start=1)
            ],
            "style": list(style_lines or []),
            "meet": {"a": dict(meet_a or {}), "b": dict(meet_b or {})},
        },
        ensure_ascii=False,
    )


def match_reasons_input(name_a: str, areas_a: dict[str, Any], name_b: str, areas_b: dict[str, Any], comparable: tuple[str, ...]) -> str:
    """Judge v1 input: the vibe lines alone."""
    return evidence_pack(name_a, areas_a, name_b, areas_b, comparable)


def allowed_sources(
    comparable: tuple[str, ...], touchpoints: list[dict[str, Any]], areas_a: dict[str, Any], areas_b: dict[str, Any]
) -> tuple[dict[str, str], dict[str, str]]:
    """(sources a reason may name, sources a clash may name) -> the text behind each, for the
    word check. Reasons: shareable areas and touchpoints with reason_ok. Clash: every comparable
    area and every touchpoint."""
    clash: dict[str, str] = {}
    reason: dict[str, str] = {}
    for area_id in comparable:
        text = f"{line_text(areas_a.get(area_id))} {line_text(areas_b.get(area_id))}"
        clash[f"area:{area_id}"] = text
        if area_id not in PRIVATE_AREA_IDS:
            reason[f"area:{area_id}"] = text
    for index, point in enumerate(touchpoints, start=1):
        text = f"{point.get('a', '')} {point.get('b', '')}"
        clash[f"touchpoint:{index}"] = text
        if point.get("reason_ok"):
            reason[f"touchpoint:{index}"] = text
    return reason, clash


def grounded(text: str, source: str) -> bool:
    """The reason uses the source's own words: two content words in common, or one when the
    reason is very short. Names and function words do not count."""
    words = _content_words(text)
    if not words:
        return False
    shared = words & _content_words(source)
    return len(shared) >= 2 or (len(shared) >= 1 and len(words) <= 4)


def validate_match_judgement(raw: Any, comparable: tuple[str, ...], touchpoints: list[dict[str, Any]], areas_a: dict[str, Any], areas_b: dict[str, Any]) -> dict[str, Any]:
    """Judge v2 output: a reason, difference or icebreaker survives only with an allowed source and
    words from it; a clash may name any comparable source; the rest is cleaned and bounded."""
    data = raw if isinstance(raw, dict) else {}
    reason_sources, clash_sources = allowed_sources(comparable, touchpoints, areas_a, areas_b)
    fit = str(data.get("fit") or "maybe").lower()
    if fit not in FITS:
        fit = "maybe"
    seen: set[str] = set()
    reasons: list[dict[str, str]] = []
    for item in data.get("reasons") or []:
        if not isinstance(item, dict):
            continue
        source, text = str(item.get("source") or ""), _clean(item.get("text"))
        if source in reason_sources and source not in seen and text and grounded(text, reason_sources[source]):
            seen.add(source)
            reasons.append(_with_area({"source": source, "text": text}))
        if len(reasons) == MAX_REASONS:
            break
    difference = data.get("difference")
    if isinstance(difference, dict) and str(difference.get("source") or "") in reason_sources and _clean(difference.get("text")):
        difference = _with_area({"source": str(difference["source"]), "text": _clean(difference["text"])})
    else:
        difference = None
    icebreaker = _clean(data.get("icebreaker")) or None
    why_not = _clean(data.get("why_not")) or None
    clash = data.get("clash")
    if isinstance(clash, dict) and str(clash.get("source") or "") in clash_sources and _clean(clash.get("note")):
        clash = {"source": str(clash["source"]), "note": _clean(clash["note"])}
    else:
        clash = None
    meet_fit = data.get("meet_fit")
    if isinstance(meet_fit, dict) and str(meet_fit.get("level") or "").lower() in MEET_FIT_LEVELS:
        meet_fit = {"level": str(meet_fit["level"]).lower(), "line": _clean(meet_fit.get("line"))}
    else:
        meet_fit = None
    chemistry = _clean(data.get("chemistry")) or None
    if fit == "yes" and not reasons:
        fit = "maybe"
    return {
        "fit": fit, "reasons": reasons, "difference": difference, "icebreaker": icebreaker, "why_not": why_not,
        "clash": clash, "meet_fit": meet_fit, "chemistry": chemistry,
    }


async def check_compatibility(user_a: str, user_b: str, *, model: str | None = None) -> MatchCheck:
    """Load both cards, build the evidence pack, and ask the judge when there is enough. With too
    little in common, fit is "unknown" and no model call is made."""
    from agent.providers import judge_match
    from storage import get_user_profile, get_user_style, get_vibe_card, private_matching_allowed

    from .readiness import match_readiness
    from .style import pair_style_lines
    from .touchpoints import pair_touchpoints

    card_a, card_b = get_vibe_card(user_a), get_vibe_card(user_b)
    both_private = private_matching_allowed(card_a) and private_matching_allowed(card_b)
    comparable = comparable_areas(card_a["areas"], card_b["areas"], both_private_allowed=both_private)
    score = compatibility_score(card_a["areas"], card_b["areas"], comparable)
    if len(comparable) < MIN_COMPARABLE_AREAS:
        return MatchCheck("unknown", score, comparable, why_not=f"only {len(comparable)} areas to compare; needs {MIN_COMPARABLE_AREAS}")
    name_a, name_b = _first_name(get_user_profile(user_a), "A"), _first_name(get_user_profile(user_b), "B")
    points = [point.as_dict() for point in pair_touchpoints(user_a, user_b)]
    style_lines = pair_style_lines(get_user_style(user_a) or {}, get_user_style(user_b) or {}, name_a, name_b)
    meet_a, meet_b = match_readiness(user_a).facts_known, match_readiness(user_b).facts_known
    # The two people go in random order: a pairwise judge leans towards whoever comes first.
    swapped = random.random() < 0.5
    first, second = ((name_b, card_b["areas"], meet_b), (name_a, card_a["areas"], meet_a)) if swapped else ((name_a, card_a["areas"], meet_a), (name_b, card_b["areas"], meet_b))
    pack_points = [{**point, "a": point["b"], "b": point["a"]} for point in points] if swapped else points
    raw = await judge_match(
        evidence_pack(first[0], first[1], second[0], second[1], comparable, touchpoints=pack_points, style_lines=style_lines, meet_a=first[2], meet_b=second[2]),
        conversation_id=f"match:{user_a}:{user_b}",
        model=model,
    )
    checked = validate_match_judgement(raw, comparable, points, card_a["areas"], card_b["areas"])
    return MatchCheck(
        checked["fit"], score, comparable, checked["reasons"], checked["difference"], checked["icebreaker"], checked["why_not"],
        clash=checked["clash"], meet_fit=checked["meet_fit"], chemistry=checked["chemistry"], touchpoints=points, style_lines=style_lines,
    )


_STOP = frozenset("and the for but not are was one two both they them their there with that this from have what when will would could about like more than into just also very".split())


def _content_words(text: str) -> set[str]:
    """Words of three letters or more, with plural and tense endings dropped so "loves" meets "love"."""
    return {_stem(word) for word in re.findall(r"[a-z\u0900-\u097f]+", text.lower()) if len(word) >= 3 and word not in _STOP}


def _stem(word: str) -> str:
    for ending in ("ing", "ed", "es", "s"):
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[: -len(ending)]
    return word


def _clean(value: Any) -> str:
    return " ".join(str(value).split())[:MAX_REASON_CHARS] if isinstance(value, str) else ""


def _with_area(item: dict[str, str]) -> dict[str, str]:
    """Older readers look for "area"; keep it on area-sourced items."""
    if item["source"].startswith("area:"):
        item["area"] = item["source"][5:]
    return item


def _first_name(profile: dict[str, Any] | None, fallback: str) -> str:
    return str((profile or {}).get("display_name") or fallback).split()[0]


__all__ = [
    "JUDGE_VERSION",
    "MATCH_JUDGE_SYSTEM_PROMPT",
    "MATCH_REASONS_SYSTEM_PROMPT",
    "MIN_COMPARABLE_AREAS",
    "MatchCheck",
    "allowed_sources",
    "check_compatibility",
    "comparable_areas",
    "compatibility_score",
    "evidence_pack",
    "grounded",
    "match_reasons_input",
    "shareable_areas",
    "validate_match_judgement",
    "validate_match_reasons",
]
