"""The pick: from every judged pair in a pool to a proposal where each ready person appears once.

Code only. It drops what cannot work (a clash, fit "no", too little to compare), orders the rest
(fit yes before maybe, more reasons, an easy meet before an unknown or awkward one, fewer style
gaps, then the shortlist score) and walks the list taking a pair when both people are still free.
Left-over people form one group of three or four when there are enough, else they wait a week.
The operator sees the proposal and confirms, swaps or drops before anyone hears a word.

Every judged pair is stored as a `candidate` so a rerun reuses the judgement for a week, and so
"never propose this pair again" has a record to check. Picked pairs become `proposed`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from itertools import combinations
from typing import Any

from agent.shared.clock import utc_now
from agent.shared.timeline import parse_time

logger = logging.getLogger(__name__)

# Fewer ready people than this and the match day says "one more week".
MIN_READY = 3
GROUP_SIZE = 4
# A judgement this old is made again: cards change in a week.
CANDIDATE_FRESH = timedelta(days=7)
# Pairs with a past in one of these are never proposed again; "expired" may come back once.
NEVER_AGAIN = frozenset({"proposed", "asked", "introduced", "met", "still_talking", "declined", "no_show"})
# A person in a pair at one of these stages has this week's match already and is not picked again.
BUSY = frozenset({"proposed", "asked", "introduced"})
_FIT_ORDER = {"yes": 0, "maybe": 1}
_MEET_ORDER = {"easy": 0, "unknown": 1, "awkward": 2}


@dataclass(frozen=True)
class Candidate:
    pair_id: str
    user_a: str
    user_b: str
    check: dict[str, Any]
    gaps: tuple[str, ...] = ()

    @property
    def users(self) -> frozenset[str]:
        return frozenset((self.user_a, self.user_b))

    def drop_reason(self) -> str | None:
        fit = str(self.check.get("fit") or "unknown")
        if self.check.get("clash"):
            return "clash"
        if fit == "no":
            return "fit no"
        if fit not in _FIT_ORDER:
            return "too little to compare"
        return None

    def sort_key(self) -> tuple:
        meet = str((self.check.get("meet_fit") or {}).get("level") or "unknown")
        return (
            _FIT_ORDER.get(str(self.check.get("fit")), 9),
            -len(self.check.get("reasons") or []),
            _MEET_ORDER.get(meet, 1),
            len(self.gaps),
            -int(self.check.get("score") or 0),
        )


@dataclass
class Proposal:
    pairs: list[Candidate] = field(default_factory=list)
    group: list[str] = field(default_factory=list)
    waiting: list[str] = field(default_factory=list)
    busy: list[str] = field(default_factory=list)
    dropped: list[tuple[Candidate, str]] = field(default_factory=list)
    judged: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "pairs": [{"pair_id": c.pair_id, "user_a": c.user_a, "user_b": c.user_b, "fit": c.check.get("fit"), "reasons": c.check.get("reasons") or [], "difference": c.check.get("difference"), "meet_fit": c.check.get("meet_fit"), "chemistry": c.check.get("chemistry"), "gaps": list(c.gaps)} for c in self.pairs],
            "group": list(self.group),
            "waiting": list(self.waiting),
            "busy": list(self.busy),
            "dropped": [{"pair_id": c.pair_id, "user_a": c.user_a, "user_b": c.user_b, "why": why} for c, why in self.dropped],
            "judged": self.judged,
        }


def rank_candidates(candidates: list[Candidate]) -> tuple[list[Candidate], list[tuple[Candidate, str]]]:
    """(kept, best first), (dropped, why)."""
    kept, dropped = [], []
    for candidate in candidates:
        why = candidate.drop_reason()
        (dropped.append((candidate, why)) if why else kept.append(candidate))
    kept.sort(key=Candidate.sort_key)
    return kept, dropped


def greedy_pairs(kept: list[Candidate]) -> list[Candidate]:
    """Walk the ranked list; take a pair when both people are still free."""
    taken: set[str] = set()
    picked = []
    for candidate in kept:
        if candidate.user_a in taken or candidate.user_b in taken:
            continue
        taken |= candidate.users
        picked.append(candidate)
    return picked


def thin_week_group(left: list[str], kept: list[Candidate]) -> list[str]:
    """Up to four left-over people who each have at least one kept pair with another of them;
    empty under three."""
    pool = set(left)
    links = {user: sum(1 for c in kept if user in c.users and c.users <= pool) for user in left}
    linked = sorted((user for user in left if links[user]), key=lambda user: -links[user])
    group = linked[:GROUP_SIZE]
    return group if len(group) >= 3 else []


def propose(ready: list[str], candidates: list[Candidate]) -> Proposal:
    """The whole pick as a pure function over ready people and their judged pairs."""
    if len(ready) < MIN_READY:
        return Proposal(waiting=list(ready), judged=len(candidates))
    kept, dropped = rank_candidates(candidates)
    pairs = greedy_pairs(kept)
    matched = {user for c in pairs for user in c.users}
    left = [user for user in ready if user not in matched]
    group = thin_week_group(left, kept)
    waiting = [user for user in left if user not in group]
    return Proposal(pairs=pairs, group=group, waiting=waiting, dropped=dropped, judged=len(candidates))


def eligible_pairs(ready: list[str], history: list[dict[str, Any]]) -> list[tuple[str, str, dict[str, Any] | None]]:
    """Pairs of ready people the pool may still propose, with a fresh stored judgement when one exists."""
    past: dict[frozenset[str], list[dict[str, Any]]] = {}
    for pair in history:
        past.setdefault(frozenset((pair["user_a"], pair["user_b"])), []).append(pair)
    now = utc_now()
    out = []
    for a, b in combinations(sorted(ready), 2):
        rows = past.get(frozenset((a, b)), [])
        if any(row["status"] in NEVER_AGAIN for row in rows):
            continue
        if sum(1 for row in rows if row["status"] == "expired") >= 1 and any(((row.get("plan") or {}).get("expired_count") or 0) >= 1 and row["status"] == "expired" for row in rows):
            # Asked once and nobody answered: one more try, not more.
            if sum(1 for row in rows if row["status"] == "expired") >= 2:
                continue
        fresh = None
        for row in rows:
            if row["status"] == "candidate":
                updated = parse_time(row.get("updated_at"))
                if updated and now - updated <= CANDIDATE_FRESH and row.get("check"):
                    fresh = row
        out.append((a, b, fresh))
    return out


async def pick_pool(pool_id: str, *, created_by: str | None = None) -> Proposal:
    """Judge what needs judging, store candidates, mark the picked pairs proposed, return the proposal."""
    from storage import get_user_style, list_match_pairs, match_pool_members_of, save_match_pair, set_match_pair_status

    from .compatibility import check_compatibility
    from .readiness import match_readiness
    from .style import style_gaps

    members = [m["user_id"] for m in match_pool_members_of(pool_id)]
    history = list_match_pairs(pool_id)
    busy = {user for pair in history if pair["status"] in BUSY for user in (pair["user_a"], pair["user_b"])}
    ready = [user_id for user_id in members if user_id not in busy and match_readiness(user_id).ready]
    if len(ready) < MIN_READY:
        return Proposal(waiting=ready, busy=sorted(busy & set(members)))
    styles = {user_id: get_user_style(user_id) or {} for user_id in ready}
    candidates: list[Candidate] = []
    judged = 0
    for a, b, fresh in eligible_pairs(ready, history):
        if fresh is not None:
            check, pair_id = fresh["check"], fresh["id"]
        else:
            check = (await check_compatibility(a, b)).as_dict()
            pair_id = save_match_pair(pool_id, a, b, check, created_by=created_by, status="candidate")["id"]
            judged += 1
        candidates.append(Candidate(pair_id, a, b, check, style_gaps(styles[a], styles[b])))
    proposal = propose(ready, candidates)
    proposal.judged = judged
    proposal.busy = sorted(busy & set(members))
    for candidate in proposal.pairs:
        set_match_pair_status(candidate.pair_id, "proposed")
    logger.info("agent.matching.pick pool_id=%s ready=%s judged=%s pairs=%s group=%s waiting=%s", pool_id, len(ready), judged, len(proposal.pairs), len(proposal.group), len(proposal.waiting))
    return proposal


__all__ = ["BUSY", "CANDIDATE_FRESH", "GROUP_SIZE", "MIN_READY", "NEVER_AGAIN", "Candidate", "Proposal", "eligible_pairs", "greedy_pairs", "pick_pool", "propose", "rank_candidates", "thin_week_group"]
