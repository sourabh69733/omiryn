"""The operator's view of one pool: who is ready, what can be shown of them, and which pairs look
worth a closer look. Only non-private vibe lines ever reach the operator; private areas are
weighed by the compatibility check, never shown.

A stored pair holds more than the operator may read: the check keeps the memory statements the
judge compared (touchpoints) and what the judge wrote about a clash, and the plan keeps the notes
taken when a person answered. operator_pair is the one place that decides what leaves: what the
two people will be told anyway, what the design gives the operator (fit, the meet line, the
chemistry line), and counts, states and times for the rest.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

from agent.shared.vibe import PRIVATE_AREA_IDS, VIBE_AREA_IDS, line_text

from .compatibility import check_compatibility, comparable_areas, compatibility_score
from .readiness import match_readiness

SUGGESTION_LIMIT = 10


def operator_check(check: dict[str, Any] | None) -> dict[str, Any] | None:
    """The check without anyone's own words: reasons, difference and icebreaker are what both
    people hear; a clash is a flag, never its note; touchpoints and style lines are counts."""
    if not check:
        return None
    fit = check.get("fit")
    return {
        "version": check.get("version"),
        "fit": fit,
        "score": check.get("score"),
        "comparable": list(check.get("comparable") or []),
        "reasons": [{key: reason[key] for key in ("source", "area", "text") if reason.get(key)} for reason in check.get("reasons") or []],
        "difference": {key: check["difference"][key] for key in ("source", "area", "text") if check["difference"].get(key)} if check.get("difference") else None,
        "icebreaker": check.get("icebreaker"),
        "meet_fit": check.get("meet_fit"),
        "chemistry": check.get("chemistry"),
        "clash": bool(check.get("clash")),
        # Written by code only when there was too little to compare; the judge's own "why not" may lean on a private area.
        "why_not": check.get("why_not") if fit == "unknown" else None,
        "mutual": check.get("mutual"),
        "views": check.get("views"),
        "touchpoints": len(check.get("touchpoints") or []),
        "style_lines": len(check.get("style_lines") or []),
    }


def operator_plan(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    """The plan without the notes: where and when, who was told and whether it reached them, who
    answered what and when, and what each said came of it."""
    if plan is None:
        return None
    told = plan.get("told") or {}
    answers = plan.get("answers") or {}
    return {
        "place": plan.get("place"),
        "when": plan.get("when"),
        "meet_at": plan.get("meet_at"),
        "asked_at": plan.get("asked_at"),
        "answer_by": plan.get("answer_by"),
        "expired_count": int(plan.get("expired_count") or 0),
        "set_by": plan.get("set_by"),
        "closed_by": plan.get("closed_by"),
        "told": {user_id: {key: note.get(key) for key in ("at", "sent", "failed", "attempts", "plan_at") if note.get(key) is not None} for user_id, note in told.items() if isinstance(note, dict)},
        "answers": {user_id: {"answer": answer.get("answer"), "at": answer.get("at")} for user_id, answer in answers.items() if isinstance(answer, dict)},
        "outcomes": [{"user_id": item.get("user_id"), "outcome": item.get("outcome"), "at": item.get("at")} for item in plan.get("outcomes") or [] if isinstance(item, dict)],
    }


def operator_pair(pair: dict[str, Any]) -> dict[str, Any]:
    """One stored pair as the operator may read it; every admin answer that carries a pair uses this."""
    return {**pair, "check": operator_check(pair.get("check")), "plan": operator_plan(pair.get("plan"))}


def pick_run_view(run: dict[str, Any] | None) -> dict[str, Any] | None:
    """A pick run as the operator reads it: where it stands and, once done, the proposal. The run
    row holds ids; what may be read of each picked pair is filled in here from the stored pair."""
    if run is None:
        return None
    from storage import get_match_pair

    progress = run.get("progress") or {}
    view: dict[str, Any] = {
        "id": run["id"], "pool_id": run["pool_id"], "status": run["status"], "error": run.get("error"), "created_by": run.get("created_by"),
        "created_at": run["created_at"], "updated_at": run["updated_at"], "finished_at": run.get("finished_at"),
        "progress": {"passes": int(progress.get("passes") or 0), "judged": int(progress.get("judged") or 0), "left": progress.get("left"), "failed_calls": sum((progress.get("failures") or {}).values())},
        "proposal": None,
    }
    result = run.get("result")
    if result is None:
        return view
    pairs = []
    for item in result.get("pairs") or []:
        pair = get_match_pair(item["pair_id"])
        check = operator_check((pair or {}).get("check")) or {}
        pairs.append({
            **item, "status": (pair or {}).get("status"), "fit": check.get("fit"), "reasons": check.get("reasons") or [], "difference": check.get("difference"),
            "meet_fit": check.get("meet_fit"), "chemistry": check.get("chemistry"),
        })
    view["proposal"] = {**result, "pairs": pairs}
    return view


def pool_view(pool_id: str) -> dict[str, Any] | None:
    from storage import blocked_match_pairs, get_match_pool, get_user_profile, get_vibe_card, list_match_pairs, match_chat_counts, match_pool_members_of, private_matching_allowed

    pool = get_match_pool(pool_id)
    if pool is None:
        return None
    members = []
    cards: dict[str, dict[str, Any]] = {}
    for member in match_pool_members_of(pool_id):
        user_id = member["user_id"]
        card = get_vibe_card(user_id)
        cards[user_id] = card
        readiness = match_readiness(user_id)
        profile = get_user_profile(user_id) or {}
        members.append(
            {
                "user_id": user_id,
                "name": profile.get("display_name") or "",
                "city": profile.get("city"),
                "joined_at": member["joined_at"],
                "readiness": readiness.as_dict(),
                # What the operator may read: never the private areas.
                "lines": {area: line_text(card["areas"][area]) for area in VIBE_AREA_IDS if area not in PRIVATE_AREA_IDS and line_text(card["areas"].get(area))},
            }
        )
    pairs = list_match_pairs(pool_id)
    # How much each introduced pair has written to each other: counts and times, never the words.
    chats = match_chat_counts([pair["id"] for pair in pairs if pair.get("introduced_at")])
    pairs = [{**operator_pair(pair), "chat": chats.get(pair["id"])} for pair in pairs]
    paired = {frozenset((pair["user_a"], pair["user_b"])) for pair in pairs} | blocked_match_pairs([m["user_id"] for m in members])
    ready = [m["user_id"] for m in members if m["readiness"]["ready"]]
    suggestions = []
    for a, b in combinations(ready, 2):
        if frozenset((a, b)) in paired:
            continue
        both_private = private_matching_allowed(cards[a]) and private_matching_allowed(cards[b])
        comparable = comparable_areas(cards[a]["areas"], cards[b]["areas"], both_private_allowed=both_private)
        suggestions.append({"user_a": a, "user_b": b, "score": compatibility_score(cards[a]["areas"], cards[b]["areas"], comparable), "comparable": len(comparable)})
    suggestions.sort(key=lambda item: (-item["score"], -item["comparable"]))
    return {
        "pool": pool,
        "members": members,
        "ready_count": len(ready),
        "pairs": pairs,
        "suggestions": suggestions[:SUGGESTION_LIMIT],
    }


async def propose_pair(pool_id: str, user_a: str, user_b: str, *, created_by: str | None = None) -> dict[str, Any]:
    """Run the compatibility check for two members and record the pair as proposed."""
    from storage import match_block_between, match_pool_members_of, save_match_pair

    members = {m["user_id"] for m in match_pool_members_of(pool_id)}
    if user_a == user_b or user_a not in members or user_b not in members:
        raise ValueError("both users must be members of the pool, and different")
    if match_block_between(user_a, user_b):
        raise ValueError("these two cannot be paired")
    from .choose import judge_version

    if judge_version() == 3:
        # The choosing judge, each looking at the other alone; notes first, so it reads today's.
        from .choose import load_person
        from .mutual import check_two
        from .notes import rebuild_due, rebuild_match_notes

        for user_id in (user_a, user_b):
            if rebuild_due(user_id):
                await rebuild_match_notes(user_id)
        from .common import mark_common

        everyone = await mark_common({user_id: load_person(user_id) for user_id in members})
        return save_match_pair(pool_id, user_a, user_b, await check_two(everyone[user_a], everyone[user_b]), created_by=created_by)
    check = await check_compatibility(user_a, user_b)
    return save_match_pair(pool_id, user_a, user_b, check.as_dict(), created_by=created_by)


__all__ = ["SUGGESTION_LIMIT", "operator_check", "operator_pair", "operator_plan", "pick_run_view", "pool_view", "propose_pair"]
