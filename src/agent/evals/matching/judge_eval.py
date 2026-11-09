"""Does the judge tell friends from strangers? Four runs on the same pairs.

Ground truth: pairs who are already friends (the friend compatibility check, or two people the
operator knows are friends), mixed with random pairs from the same group. Each run judges every
pair with a different amount of evidence and the report says, per run, how many known friends come
out "yes" against how many random pairs do. The run that separates them best is the one to ship.

Runs: v1_vibe (the old prompt, vibe lines only), v2_vibe (the new prompt, vibe lines only),
v2_touchpoints (plus memory touchpoints), v2_all (plus talk-style lines and meet facts).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from agent.matching.compatibility import (
    MIN_COMPARABLE_AREAS,
    PairEvidence,
    pair_evidence,
    validate_match_judgement,
    validate_match_reasons,
    shareable_areas,
)

RUNS = ("v1_vibe", "v2_vibe", "v2_touchpoints", "v2_all")


@dataclass(frozen=True)
class PairVerdict:
    user_a: str
    user_b: str
    known: bool
    run: str
    fit: str
    reasons: list[str] = field(default_factory=list)
    clash: bool = False
    chemistry: str | None = None
    error: str | None = None


@dataclass
class RunSummary:
    run: str
    known_yes: int = 0
    known_total: int = 0
    random_yes: int = 0
    random_total: int = 0
    errors: int = 0

    @property
    def known_rate(self) -> float:
        return self.known_yes / self.known_total if self.known_total else 0.0

    @property
    def random_rate(self) -> float:
        return self.random_yes / self.random_total if self.random_total else 0.0

    @property
    def separation(self) -> float:
        """Known-friend yes rate minus random-pair yes rate; higher is better, 0 is no signal."""
        return self.known_rate - self.random_rate


def pick_pairs(known: list[tuple[str, str]], users: list[str], *, random_pairs: int, seed: int = 7) -> list[tuple[str, str, bool]]:
    """The known pairs plus up to `random_pairs` other pairs among the users, seeded so a rerun
    judges the same pairs."""
    known_set = {frozenset(pair) for pair in known}
    others = [pair for pair in combinations(sorted(set(users)), 2) if frozenset(pair) not in known_set]
    random.Random(seed).shuffle(others)
    return [(a, b, True) for a, b in known] + [(a, b, False) for a, b in others[:random_pairs]]


# An evaluation can wait longer than a live check: a slow answer is better than a lost pair.
JUDGE_TIMEOUT_SECONDS = 120.0


async def judge_pair(evidence: PairEvidence, run: str, *, user_a: str, user_b: str, model: str | None = None) -> dict[str, Any]:
    """One judged pair under one run; the same checks the live check applies."""
    from agent.providers import judge_match, write_match_reasons

    if run == "v1_vibe":
        raw = await write_match_reasons(
            evidence.pack(touchpoints=False, style=False, meet=False),
            conversation_id=f"match-eval:{user_a}:{user_b}",
            model=model,
            timeout_seconds=JUDGE_TIMEOUT_SECONDS,
        )
        checked = validate_match_reasons(raw, shareable_areas(evidence.comparable))
        return {**checked, "clash": None, "chemistry": None}
    pack = evidence.pack(touchpoints=run != "v2_vibe", style=run == "v2_all", meet=run == "v2_all")
    raw = await judge_match(pack, conversation_id=f"match-eval:{user_a}:{user_b}", model=model, timeout_seconds=JUDGE_TIMEOUT_SECONDS)
    points = evidence.touchpoints if run != "v2_vibe" else []
    return validate_match_judgement(raw, evidence.comparable, points, evidence.areas_a, evidence.areas_b)


async def evaluate(
    pairs: list[tuple[str, str, bool]], *, runs: tuple[str, ...] = RUNS, model: str | None = None
) -> tuple[list[PairVerdict], list[RunSummary]]:
    verdicts: list[PairVerdict] = []
    summaries = {run: RunSummary(run) for run in runs}
    for user_a, user_b, known in pairs:
        evidence = pair_evidence(user_a, user_b)
        for run in runs:
            summary = summaries[run]
            if len(evidence.comparable) < MIN_COMPARABLE_AREAS:
                verdicts.append(PairVerdict(user_a, user_b, known, run, "unknown", error=f"only {len(evidence.comparable)} comparable areas"))
                summary.errors += 1
                continue
            try:
                checked = await judge_pair(evidence, run, user_a=user_a, user_b=user_b, model=model)
            except Exception as error:  # a failed call is a result too
                verdicts.append(PairVerdict(user_a, user_b, known, run, "error", error=type(error).__name__))
                summary.errors += 1
                continue
            verdicts.append(
                PairVerdict(user_a, user_b, known, run, checked["fit"], [r["text"] for r in checked["reasons"]], bool(checked.get("clash")), checked.get("chemistry"))
            )
            if known:
                summary.known_total += 1
                summary.known_yes += checked["fit"] == "yes"
            else:
                summary.random_total += 1
                summary.random_yes += checked["fit"] == "yes"
    return verdicts, [summaries[run] for run in runs]


def report(verdicts: list[PairVerdict], summaries: list[RunSummary], *, show_reasons: bool = False) -> str:
    """Markdown: one table of runs, then every pair's fit per run. Reasons only when asked, since
    they quote what people said."""
    lines = ["| run | known friends said yes | random pairs said yes | separation | errors |", "|---|---|---|---|---|"]
    for s in summaries:
        lines.append(f"| {s.run} | {s.known_yes}/{s.known_total} ({s.known_rate:.0%}) | {s.random_yes}/{s.random_total} ({s.random_rate:.0%}) | {s.separation:+.2f} | {s.errors} |")
    best = max(summaries, key=lambda s: s.separation, default=None)
    if best is not None and best.known_total:
        lines += ["", f"Best separation: `{best.run}` ({best.separation:+.2f})."]
    lines += ["", "| pair | known | " + " | ".join(s.run for s in summaries) + " |", "|---|---|" + "---|" * len(summaries)]
    by_pair: dict[tuple[str, str, bool], dict[str, PairVerdict]] = {}
    for verdict in verdicts:
        by_pair.setdefault((verdict.user_a, verdict.user_b, verdict.known), {})[verdict.run] = verdict
    for (user_a, user_b, known), runs in by_pair.items():
        cells = []
        for s in summaries:
            verdict = runs.get(s.run)
            cell = verdict.fit if verdict else "-"
            if verdict and verdict.clash:
                cell += " (clash)"
            if verdict and verdict.error:
                cell += f" ({verdict.error})"
            cells.append(cell)
        lines.append(f"| {user_a} + {user_b} | {'yes' if known else 'no'} | " + " | ".join(cells) + " |")
    if show_reasons:
        lines.append("")
        for verdict in verdicts:
            for reason in verdict.reasons:
                lines.append(f"- {verdict.run} · {verdict.user_a} + {verdict.user_b}: {reason}")
            if verdict.chemistry:
                lines.append(f"- {verdict.run} · {verdict.user_a} + {verdict.user_b} · chemistry: {verdict.chemistry}")
    return "\n".join(lines)


__all__ = ["RUNS", "PairVerdict", "RunSummary", "evaluate", "judge_pair", "pick_pairs", "report"]
