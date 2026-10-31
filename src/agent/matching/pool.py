"""The operator's view of one pool: who is ready, what can be shown of them, and which pairs look
worth a closer look. Only non-private vibe lines ever reach the operator; private areas are
weighed by the compatibility check, never shown.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

from agent.shared.vibe import PRIVATE_AREA_IDS, VIBE_AREA_IDS, line_text

from .compatibility import check_compatibility, comparable_areas, compatibility_score
from .readiness import match_readiness

SUGGESTION_LIMIT = 10


def pool_view(pool_id: str) -> dict[str, Any] | None:
    from storage import get_match_pool, get_user_profile, get_vibe_card, list_match_pairs, match_pool_members_of, private_matching_allowed

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
    paired = {frozenset((pair["user_a"], pair["user_b"])) for pair in pairs}
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
    from storage import match_pool_members_of, save_match_pair

    members = {m["user_id"] for m in match_pool_members_of(pool_id)}
    if user_a == user_b or user_a not in members or user_b not in members:
        raise ValueError("both users must be members of the pool, and different")
    check = await check_compatibility(user_a, user_b)
    return save_match_pair(pool_id, user_a, user_b, check.as_dict(), created_by=created_by)


__all__ = ["SUGGESTION_LIMIT", "pool_view", "propose_pair"]
