"""The two-sided pick: a pair is made only when each person, looking at the other, calls it strong.

The choosing judge (agent.matching.choose) answers for one person. With little known about
someone it can call a thin overlap strong, and it has no way to tell whether the other person
would want the introduction too. So every ready person gets their own ranking, and a pair goes
ahead in one of two ways:

- both_best: each is the other's best.
- confirmed_back: A's best is B, B's best is someone else or nobody, and B, shown A alone, calls
  the pull strong.

A clash seen from either side drops the pair. Code then takes pairs so that nobody is in two:
both_best first, then the ones where B had ranked A highest. Everyone else waits; "nobody this
time" is a normal result. The reasons told to both come from both sides' answers.

Nothing here reads or writes storage: it works on people already loaded, so the pick
(agent.matching.pick) and the evaluation can both run it.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from agent.memory_engine.memories.ranking import embedding_similarity

from .choose import CHOOSE_VERSION, MAX_CANDIDATES, Choice, Loaded, choose_loaded
from .compatibility import MAX_REASONS, _content_words

PARALLEL_CALLS = 4
# How many of a person's statements count towards how close two people are, for the shortlist.
_CLOSEST = 3
# Two reasons that share this much of their words say the same thing.
_SAME_REASON = 0.6


@dataclass(frozen=True)
class MutualPair:
    user_a: str
    user_b: str
    # "both_best" or "confirmed_back"; user_a is the one whose best was user_b.
    kind: str
    check: dict[str, Any]

    @property
    def users(self) -> frozenset[str]:
        return frozenset((self.user_a, self.user_b))


@dataclass
class MutualResult:
    pairs: list[MutualPair] = field(default_factory=list)
    # Each person's own ranking, for the operator and the evaluation.
    looks: dict[str, Choice] = field(default_factory=dict)
    waiting: list[str] = field(default_factory=list)
    # Pairs one side wanted and the other did not confirm, or that lost to another pair: (a, b, why).
    not_taken: list[tuple[str, str, str]] = field(default_factory=list)
    # People whose ranking or check call failed; they wait.
    errors: dict[str, str] = field(default_factory=dict)


def closeness(a: Loaded, b: Loaded) -> float:
    """How near two people's statements are in meaning, both ways: for each side, the average of
    its few best matches in the other. Code-only, for the shortlist; 0 when either has no vectors."""

    def one_way(own: Loaded, other: Loaded) -> float:
        best = sorted(
            (max((score for theirs in other.vectors.values() if (score := embedding_similarity(mine, theirs)) is not None), default=0.0) for mine in own.vectors.values()),
            reverse=True,
        )[:_CLOSEST]
        return sum(best) / len(best) if best else 0.0

    return (one_way(a, b) + one_way(b, a)) / 2 if a.vectors and b.vectors else 0.0


def shortlist(person: Loaded, others: list[Loaded], *, limit: int = MAX_CANDIDATES) -> list[Loaded]:
    """The candidates one ranking can hold. With more than fit, the closest in meaning; people
    with no vectors keep their given order after those."""
    if len(others) <= limit:
        return list(others)
    return sorted(others, key=lambda other: closeness(person, other), reverse=True)[:limit]


def pair_check(a_view: Choice, b_view: Choice, *, a: str, b: str, kind: str) -> dict[str, Any]:
    """What is stored on the pair and told to both: the shape judges v1 and v2 store (fit, reasons,
    difference, icebreaker, chemistry), written from both people's answers. A's reasons come first;
    B's are added when they say something else."""
    reasons: list[dict[str, Any]] = []
    seen: list[set[str]] = []
    for view in (a_view, b_view):
        if view.best != (b if view is a_view else a):
            continue
        for reason in view.reasons:
            words = _content_words(reason["text"])
            if any(words and len(words & other) / len(words | other) >= _SAME_REASON for other in seen):
                continue
            seen.append(words)
            reasons.append({"source": reason["mine"], "with": reason["theirs"], "text": reason["text"], **({"area": reason["area"]} if reason.get("area") else {})})
    first = a_view if a_view.best == b else b_view
    second = b_view if first is a_view else a_view
    difference = first.difference or (second.difference if second.best in (a, b) else None)
    return {
        "version": CHOOSE_VERSION,
        "fit": "yes" if reasons else "maybe",
        "mutual": kind,
        "reasons": reasons[:MAX_REASONS],
        "difference": {"source": difference["mine"], "text": difference["text"], **({"area": difference["area"]} if difference.get("area") else {})} if difference else None,
        "icebreaker": first.icebreaker or (second.icebreaker if second.best in (a, b) else None),
        "chemistry": first.chemistry or (second.chemistry if second.best in (a, b) else None),
        "why_not": None,
        "clash": None,
        "meet_fit": None,
        "score": 0,
        "views": {a: {"place": a_view.rank_of(b), "pull": a_view.pull.get(b)}, b: {"place": b_view.rank_of(a), "pull": b_view.pull.get(a)}},
    }


async def mutual_pick(
    people: dict[str, Loaded],
    allowed: Callable[[str, str], bool] | None = None,
    *,
    model: str | None = None,
    seed: int | None = None,
    timeout_seconds: float | None = 60,
) -> MutualResult:
    """Rank for everyone, confirm back where needed, and take pairs so nobody is in two.

    `allowed(a, b)` is false for two people who must not be paired (blocked, or tried before).
    """
    allowed = allowed or (lambda a, b: True)
    refs = sorted(people)
    gate = asyncio.Semaphore(PARALLEL_CALLS)
    result = MutualResult()

    async def look(ref: str, candidates: list[Loaded], salt: int) -> Choice | None:
        async with gate:
            try:
                rng = random.Random(f"{seed}:{ref}:{salt}") if seed is not None else None
                return await choose_loaded(people[ref], candidates, model=model, rng=rng, timeout_seconds=timeout_seconds)
            except Exception as error:  # one failed person must not lose the round
                result.errors[ref] = type(error).__name__
                return None

    async def ranking(ref: str) -> None:
        others = [people[other] for other in refs if other != ref and allowed(ref, other)]
        if not others:
            return
        choice = await look(ref, shortlist(people[ref], others), 0)
        if choice is not None:
            result.looks[ref] = choice

    await asyncio.gather(*(ranking(ref) for ref in refs))

    # Who wants whom, and whether the other side agrees.
    wanted = [(a, choice.best) for a, choice in sorted(result.looks.items()) if choice.best]
    found: dict[frozenset[str], MutualPair] = {}

    async def settle(a: str, b: str) -> None:
        a_view, b_look = result.looks[a], result.looks.get(b)
        if b_look is not None and b_look.best == a:
            if frozenset((a, b)) not in found:
                first, second = sorted((a, b))
                found[frozenset((a, b))] = MutualPair(first, second, "both_best", pair_check(result.looks[first], result.looks[second], a=first, b=second, kind="both_best"))
            return
        if b_look is not None and a in b_look.clashes:
            result.not_taken.append((a, b, "the other side sees a clash"))
            return
        # B did not pick A among several: ask B about A alone.
        back = await look(b, [people[a]], 1)
        if back is None:
            result.not_taken.append((a, b, "the check back failed"))
        elif back.best == a:
            found.setdefault(frozenset((a, b)), MutualPair(a, b, "confirmed_back", pair_check(a_view, back, a=a, b=b, kind="confirmed_back")))
        else:
            result.not_taken.append((a, b, "the other side did not call it strong"))

    await asyncio.gather(*(settle(a, b) for a, b in wanted))

    def order(pair: MutualPair) -> tuple:
        # both_best first; then where B had placed A highest in their own ranking; then by name so a rerun agrees.
        b_look = result.looks.get(pair.user_b)
        place = (b_look.rank_of(pair.user_a) if b_look else None) or MAX_CANDIDATES + 1
        return (pair.kind != "both_best", place, pair.user_a, pair.user_b)

    taken: set[str] = set()
    for pair in sorted(found.values(), key=order):
        if pair.users & taken:
            result.not_taken.append((pair.user_a, pair.user_b, "one of them was taken by a better pair"))
            continue
        taken |= pair.users
        result.pairs.append(pair)
    result.waiting = [ref for ref in refs if ref not in taken]
    return result


async def check_two(a: Loaded, b: Loaded, *, model: str | None = None) -> dict[str, Any]:
    """For a pair somebody chose by hand: each looks at the other alone. The stored check says
    yes only when both call it strong; one side alone is "maybe" with no reasons to tell, and a
    clash from either side is "no"."""
    a_view, b_view = await asyncio.gather(choose_loaded(a, [b], model=model), choose_loaded(b, [a], model=model))
    clash = a_view.clashes.get(b.ref) or b_view.clashes.get(a.ref)
    if a_view.best == b.ref and b_view.best == a.ref:
        return pair_check(a_view, b_view, a=a.ref, b=b.ref, kind="both_best")
    views = {a.ref: {"place": 1, "pull": a_view.pull.get(b.ref)}, b.ref: {"place": 1, "pull": b_view.pull.get(a.ref)}}
    why = clash or a_view.why_not.get(b.ref) or b_view.why_not.get(a.ref) or "not strong from both sides"
    return {
        "version": CHOOSE_VERSION, "fit": "no" if clash else "maybe", "mutual": None, "reasons": [], "difference": None, "icebreaker": None,
        "chemistry": None, "why_not": why, "clash": {"note": clash} if clash else None, "meet_fit": None, "score": 0, "views": views,
    }


__all__ = ["MutualPair", "MutualResult", "check_two", "closeness", "mutual_pick", "pair_check", "shortlist"]
