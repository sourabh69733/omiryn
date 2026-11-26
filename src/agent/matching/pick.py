"""The pick: from every judged pair in a pool to a proposal where each ready person appears once.

Code only. It drops what cannot work (a clash, fit "no", too little to compare), orders the rest
(fit yes before maybe, more reasons, an easy meet before an unknown or awkward one, fewer style
gaps, then the shortlist score) and walks the list taking a pair when both people are still free.
Left-over people form one group of three or four when there are enough, else they wait a week.
The operator sees the proposal and confirms, swaps or drops before anyone hears a word.

Every judged pair is stored as a `candidate` so a rerun reuses the judgement for a week, and so
"never propose this pair again" has a record to check. Picked pairs become `proposed`.

A real pool is hundreds of judge calls, so the pick runs as a background job in passes
(pick_pool_pass, agent.matching.pick_job): each pass judges what it can in its time and stores it;
the pass that finds nothing left to judge makes the proposal. pick_pool is the same in one go.

With MATCH_JUDGE=3 the pick is the two-sided one instead (pick_pool_mutual): ready means enough
match notes, each person ranks the others, and a pair is made only when both sides call it strong
(agent.matching.mutual). The rules around it stay: who is busy, who was tried before, who is blocked.
"""

from __future__ import annotations

import asyncio
import logging
import time
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
# An ask nobody answered may be tried once more; after this many lapses the pair is not offered again.
MAX_LAPSES = 2
# Pairs with a past in one of these are never proposed again; "expired" is counted by `lapses`.
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
    # Two-sided pick only: pairs one side wanted that did not go ahead, and why; people whose call failed.
    not_taken: list[dict[str, str]] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    # Pairs the pick could not judge (the call kept failing), so they were not weighed at all.
    not_judged: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "pairs": [{"pair_id": c.pair_id, "user_a": c.user_a, "user_b": c.user_b, "fit": c.check.get("fit"), "reasons": c.check.get("reasons") or [], "difference": c.check.get("difference"), "meet_fit": c.check.get("meet_fit"), "chemistry": c.check.get("chemistry"), "gaps": list(c.gaps)} for c in self.pairs],
            "group": list(self.group),
            "waiting": list(self.waiting),
            "busy": list(self.busy),
            "dropped": [{"pair_id": c.pair_id, "user_a": c.user_a, "user_b": c.user_b, "why": why} for c, why in self.dropped],
            "judged": self.judged,
            "not_taken": list(self.not_taken),
            "errors": dict(self.errors),
            "not_judged": list(self.not_judged),
        }

    def as_record(self) -> dict[str, Any]:
        """The proposal as the run row keeps it: ids, counts and code's own words for why. What
        the judge wrote stays on the pairs, where it is encrypted."""
        return {
            "pairs": [{"pair_id": c.pair_id, "user_a": c.user_a, "user_b": c.user_b, "gaps": list(c.gaps)} for c in self.pairs],
            "group": list(self.group),
            "waiting": list(self.waiting),
            "busy": list(self.busy),
            "dropped": [{"pair_id": c.pair_id, "user_a": c.user_a, "user_b": c.user_b, "why": why} for c, why in self.dropped],
            "judged": self.judged,
            "not_taken": list(self.not_taken),
            "errors": dict(self.errors),
            "not_judged": list(self.not_judged),
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


def lapses(rows: list[dict[str, Any]]) -> int:
    """How many times these two were asked and the ask ran out unanswered. Each pick stores a new
    row for a pair it offers again, so the rows are counted; a row the operator put back to
    proposed and asked again carries its own count."""
    return sum(max(1, int((row.get("plan") or {}).get("expired_count") or 0)) for row in rows if row["status"] == "expired")


def eligible_pairs(
    ready: list[str], history: list[dict[str, Any]], blocked: set[frozenset[str]] | None = None
) -> list[tuple[str, str, dict[str, Any] | None]]:
    """Pairs of ready people the pool may still propose, with a fresh stored judgement when one exists.

    `blocked` holds every two people where one blocked the other, in any pool: never offered again.
    """
    past: dict[frozenset[str], list[dict[str, Any]]] = {}
    for pair in history:
        past.setdefault(frozenset((pair["user_a"], pair["user_b"])), []).append(pair)
    now = utc_now()
    out = []
    for a, b in combinations(sorted(ready), 2):
        rows = past.get(frozenset((a, b)), [])
        if any(row["status"] in NEVER_AGAIN for row in rows) or (blocked and frozenset((a, b)) in blocked):
            continue
        if lapses(rows) >= MAX_LAPSES:
            continue
        fresh = None
        for row in rows:
            if row["status"] == "candidate":
                updated = parse_time(row.get("updated_at"))
                if updated and now - updated <= CANDIDATE_FRESH and row.get("check"):
                    fresh = row
        out.append((a, b, fresh))
    return out


@dataclass
class PickPass:
    """One pass of the pick. The whole pick is too long for one go on a real pool (a judge call
    per pair of ready people), so the background job (agent.matching.pick_job) runs it in passes:
    each judges what it can in its time, stores it, and says what is left. The pass that finds
    nothing left makes the proposal."""

    # Set by the last pass only.
    proposal: Proposal | None = None
    # Judgements stored in this pass.
    judged: int = 0
    # What a later pass still has to do: pairs to judge, or people whose notes wait.
    left: int = 0
    # Pairs ("a|b") whose judge call failed in this pass; the job counts them and gives up on a pair in time.
    failed: list[str] = field(default_factory=list)
    # Two-sided pick: people whose notes this pass brought up to date, or tried to.
    notes_tried: list[str] = field(default_factory=list)


def pair_key(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


async def pick_pool(pool_id: str, *, created_by: str | None = None) -> Proposal:
    """The whole pick in one go: judge what needs judging, store candidates, mark the picked pairs
    proposed, return the proposal. For tests, scripts and small pools; a web request must not wait
    on this (admin routes queue the job instead)."""
    done = await pick_pool_pass(pool_id, created_by=created_by)
    assert done.proposal is not None
    return done.proposal


async def pick_pool_pass(
    pool_id: str,
    *,
    created_by: str | None = None,
    seconds: float | None = None,
    parallel: int = 1,
    gave_up: frozenset[str] | set[str] = frozenset(),
    notes_tried: frozenset[str] | set[str] = frozenset(),
) -> PickPass:
    """One pass. With `seconds` it stops starting judge calls after that long and a failed call is
    reported, not raised; without, it runs to the end and a failure reaches the caller. `gave_up`
    names pairs the job stopped retrying; `notes_tried` the people whose notes an earlier pass did."""
    from storage import blocked_match_pairs, delete_stale_match_candidates, get_user_style, list_match_pairs, match_pool_members_of, save_match_pair, set_match_pair_status

    from .choose import judge_version
    from .compatibility import check_compatibility
    from .reads import PickReads
    from .style import style_gaps

    deadline = time.monotonic() + seconds if seconds is not None else None
    if judge_version() == 3:
        return await _mutual_pass(pool_id, created_by=created_by, deadline=deadline, notes_tried=set(notes_tried))
    # A judgement past its week is never read again; without this every match day leaves a row per pair behind.
    delete_stale_match_candidates(pool_id, utc_now() - CANDIDATE_FRESH)
    members = [m["user_id"] for m in match_pool_members_of(pool_id)]
    history = list_match_pairs(pool_id)
    busy = {user for pair in history if pair["status"] in BUSY for user in (pair["user_a"], pair["user_b"])}
    # Each person is read once for the whole pass, however many pairs they are in.
    reads = PickReads()
    ready = [user_id for user_id in members if user_id not in busy and reads.readiness(user_id).ready]
    if len(ready) < MIN_READY:
        return PickPass(proposal=Proposal(waiting=ready, busy=sorted(busy & set(members))))
    blocked = blocked_match_pairs(ready)
    todo = [(a, b) for a, b, fresh in eligible_pairs(ready, history, blocked) if fresh is None and pair_key(a, b) not in gave_up]
    done = PickPass()
    gate = asyncio.Semaphore(max(1, parallel))

    async def judge(a: str, b: str) -> None:
        async with gate:
            if deadline is not None and time.monotonic() >= deadline:
                done.left += 1
                return
            try:
                check = (await check_compatibility(a, b, reads=reads)).as_dict()
            except Exception as error:
                if seconds is None:
                    raise
                logger.warning("agent.matching.pick.judge_failed pool_id=%s error_type=%s", pool_id, type(error).__name__)
                done.failed.append(pair_key(a, b))
                done.left += 1
                return
            # Stored at once: the next pass, or a rerun after a crash, starts from here.
            save_match_pair(pool_id, a, b, check, created_by=created_by, status="candidate")
            done.judged += 1

    if parallel > 1:
        await asyncio.gather(*(judge(a, b) for a, b in todo))
    else:
        for a, b in todo:
            await judge(a, b)
    if done.left:
        return done
    # Everything that can be judged has a fresh judgement: read them back and pick.
    styles = {user_id: get_user_style(user_id) or {} for user_id in ready}
    candidates: list[Candidate] = []
    not_judged: list[dict[str, str]] = []
    for a, b, fresh in eligible_pairs(ready, list_match_pairs(pool_id), blocked):
        if fresh is None:
            not_judged.append({"user_a": a, "user_b": b, "why": "the judge call kept failing"})
            continue
        candidates.append(Candidate(fresh["id"], a, b, fresh["check"], style_gaps(styles[a], styles[b])))
    proposal = propose(ready, candidates)
    proposal.judged = done.judged
    proposal.busy = sorted(busy & set(members))
    proposal.not_judged = not_judged
    for candidate in proposal.pairs:
        set_match_pair_status(candidate.pair_id, "proposed")
    logger.info("agent.matching.pick pool_id=%s ready=%s judged=%s pairs=%s group=%s waiting=%s not_judged=%s", pool_id, len(ready), done.judged, len(proposal.pairs), len(proposal.group), len(proposal.waiting), len(not_judged))
    done.proposal = proposal
    return done


async def pick_pool_mutual(pool_id: str, *, created_by: str | None = None) -> Proposal:
    """The two-sided pick for a pool: bring everyone's match notes up to date, rank for each ready
    person, keep the pairs both sides call strong, store them as proposed."""
    done = await _mutual_pass(pool_id, created_by=created_by, deadline=None, notes_tried=set())
    assert done.proposal is not None
    return done.proposal


async def _mutual_pass(pool_id: str, *, created_by: str | None, deadline: float | None, notes_tried: set[str]) -> PickPass:
    """A pass of the two-sided pick. Bringing notes up to date is a model call per person, so it
    is the part done over passes: each pass does who it can and names them. Once nobody is left
    the ranking and the pairs are made in the same pass (the job keeps its lease alive meanwhile)."""
    from storage import blocked_match_pairs, get_user_style, list_match_pairs, match_pool_members_of, save_match_pair

    from .choose import load_person
    from .common import mark_common
    from .mutual import mutual_pick
    from .notes import match_notes_readiness, rebuild_due, rebuild_match_notes
    from .style import style_gaps

    members = [m["user_id"] for m in match_pool_members_of(pool_id)]
    history = list_match_pairs(pool_id)
    busy = {user for pair in history if pair["status"] in BUSY for user in (pair["user_a"], pair["user_b"])}
    free = [user_id for user_id in members if user_id not in busy]
    done = PickPass()
    waiting_notes = [user_id for user_id in free if user_id not in notes_tried]
    for user_id in waiting_notes:
        if deadline is not None and time.monotonic() >= deadline:
            break
        # Notes are refreshed once a day; a pick should not run on yesterday's.
        try:
            if rebuild_due(user_id):
                await rebuild_match_notes(user_id)
        except Exception as error:
            logger.warning("agent.matching.pick.notes_failed error_type=%s", type(error).__name__)
        done.notes_tried.append(user_id)
    done.left = len(waiting_notes) - len(done.notes_tried)
    if done.left:
        return done
    ready = [user_id for user_id in free if match_notes_readiness(user_id)["ready"]]
    if len(ready) < MIN_READY:
        done.proposal = Proposal(waiting=ready, busy=sorted(busy & set(members)))
        return done
    may_pair = {frozenset((a, b)) for a, b, _ in eligible_pairs(ready, history, blocked_match_pairs(ready))}
    # What is ordinary is judged over the whole group, busy people included; only the ready are ranked.
    everyone = await mark_common({user_id: load_person(user_id) for user_id in members})
    result = await mutual_pick({user_id: everyone[user_id] for user_id in ready}, lambda a, b: frozenset((a, b)) in may_pair)
    styles = {user_id: get_user_style(user_id) or {} for user_id in ready}
    proposal = Proposal(
        waiting=list(result.waiting), busy=sorted(busy & set(members)), judged=len(result.looks),
        not_taken=[{"user_a": a, "user_b": b, "why": why} for a, b, why in result.not_taken], errors=dict(result.errors),
    )
    for pair in result.pairs:
        stored = save_match_pair(pool_id, pair.user_a, pair.user_b, pair.check, created_by=created_by, status="proposed")
        proposal.pairs.append(Candidate(stored["id"], pair.user_a, pair.user_b, pair.check, style_gaps(styles[pair.user_a], styles[pair.user_b])))
    logger.info("agent.matching.pick_mutual pool_id=%s ready=%s ranked=%s pairs=%s waiting=%s errors=%s", pool_id, len(ready), len(result.looks), len(proposal.pairs), len(proposal.waiting), len(result.errors))
    done.judged = len(result.looks)
    done.proposal = proposal
    return done


__all__ = [
    "BUSY", "CANDIDATE_FRESH", "GROUP_SIZE", "MAX_LAPSES", "MIN_READY", "NEVER_AGAIN", "Candidate", "PickPass", "Proposal", "eligible_pairs", "greedy_pairs",
    "lapses", "pair_key", "pick_pool", "pick_pool_mutual", "pick_pool_pass", "propose", "rank_candidates", "thin_week_group",
]
