"""Can the choosing judge (agent.matching.choose) tell a good introduction from a bad one?

Three tests on made-up people whose right answer is planted:

- with the friend: the person's planted friend, a decoy and three others are the candidates. The
  friend should come first. The decoy shares the surface (same hobbies, same hours) but does what
  the person cannot stand, so it should be marked as a clash and come last.
- without the friend: the decoy and four others. Nobody here is a good introduction, so the right
  answer is "nobody"; choosing the decoy is the worst answer.
- one at a time: a single candidate per call, which is how judges v1 and v2 are asked. It shows how
  often a judge that only approves or rejects says yes to the wrong person.

Two sources. "fixtures" builds each person's notes straight from the persona text, so the judge is
tested alone with good evidence. "db" reads people seeded through the real pipeline
(scripts/evals/seed_match_personas.py), so the result also depends on what memory kept of them.
"""

from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from agent.matching.choose import Choice, Person, Note, choose_among

from .personas import MATCH_PERSONAS

TESTS = ("with_friend", "without_friend", "one_at_a_time")
OTHERS_WITH_FRIEND = 3
OTHERS_WITHOUT_FRIEND = 4
# An evaluation can wait longer than a live check.
TIMEOUT_SECONDS = 120.0
PARALLEL_CALLS = 4


@dataclass(frozen=True)
class Decoy:
    """Someone who looks like a match for two of the personas on the surface and is not one."""

    id: str
    name: str
    near: tuple[str, str]
    persona: str


_PUNE = "You moved to Pune alone for work a few weeks ago and live in a PG."

DECOYS: tuple[Decoy, ...] = (
    Decoy(
        id="vikram",
        name="Vikram",
        near=("aarav", "kabir"),
        persona=(
            f"You are Vikram, 26, a sales engineer at a SaaS company in Baner. {_PUNE} It is in Aundh. You write in "
            "Hinglish with lots of emojis and caps. You follow the Premier League (Chelsea) and the IPL, play FIFA at "
            "night, and love street food. Night owl, free after 9 pm and on Saturday nights. You eat everything. You post "
            "everything you do on Instagram: every match screening, every plate, every night out is a story, and you ask "
            "friends to retake photos until they look good. You love clubs, big groups and loud nights, and get bored "
            "with two or three people. You say yes to every plan and drop out of half of them on the day when something "
            "better comes up; you think people who mind that are too serious. You talk a lot about your targets, your "
            "bonus and the hustle. When a friend is annoyed you laugh it off and change the topic. You keep in touch by "
            "tagging people in posts. What you want from a friend: a crew to be seen with at screenings and parties."
        ),
    ),
    Decoy(
        id="ananya",
        name="Ananya",
        near=("meera", "sanya"),
        persona=(
            f"You are Ananya, 26, a brand designer at an agency in Koregaon Park. {_PUNE} It is in Kalyani Nagar. You "
            "write in English, properly punctuated. You trek in the Sahyadris, read fiction and hop cafes with a book. "
            "Early riser, free on weekend mornings. Vegetarian, happy to spend 500 on brunch. What you enjoy most with "
            "friends is gossip: who is dating whom at work, who got fat, who married badly, and you say plainly what "
            "you think of other people's choices, their clothes, their jobs and their partners. You think people who "
            "do not gossip are boring or hiding something. You never plan: you decide on the morning itself and expect "
            "friends to be free, and you find lists and plans made weeks ahead suffocating. When a friend is hurt you "
            "tell them they are too sensitive. You keep in touch through long calls about other people. What you "
            "want from a friend: someone to trek with and tell everything about everyone."
        ),
    ),
    Decoy(
        id="nikhil",
        name="Nikhil",
        near=("rohan", "dev"),
        persona=(
            f"You are Nikhil, 28, a product manager at a startup in Magarpatta. {_PUNE} It is in Hadapsar. You write in "
            "English, long messages, many exclamation marks. You shoot street photos, listen to indie bands and cook on "
            "Sundays. Free on weekday evenings after 7 and Sunday afternoons. You eat everything. You need to be the "
            "centre of every room: you tell your stories loudly, you show every photo you take to everyone and post "
            "them with long captions about your eye for detail, and you talk about your salary and the famous people "
            "you have met. You want a friend to reply within minutes, call every day, and you sulk and say so when "
            "someone goes quiet for a day. Silence on a walk makes you uneasy, so you fill it. When upset you raise it "
            "at once and loudly, in front of others if needed. What you want from a friend: someone always available "
            "who admires your photos and comes to every plan you make."
        ),
    ),
)


def third_person(text: str) -> str:
    """Persona text is written to the model that plays the person ("You follow..."); the judge needs
    it about them ("They follow..."). Grammar is rough in places and that is fine for a reader."""
    swaps = (("yourself", "themself"), ("yours", "theirs"), ("your", "their"), ("you are", "they are"), ("you", "they"))
    for old, new in swaps:
        text = re.sub(rf"\b{old}\b", new, text)
        text = re.sub(rf"\b{old.capitalize()}\b", new.capitalize(), text)
    return text


def fixture_person(ref: str, name: str, persona: str, *, sample: int | None = None, rng: random.Random | None = None) -> Person:
    """A person whose notes are the persona's own sentences. `sample` keeps only that many, picked
    at random, to see how the judge does when it knows less."""
    sentences = [third_person(part.strip()) for part in re.split(r"(?<=[.!?])\s+", persona) if part.strip()]
    # The first sentence carries the name and the job; keep it so a sampled person is still someone.
    head, rest = sentences[:1], sentences[1:]
    if sample is not None and sample < len(rest):
        keep = sorted((rng or random).sample(range(len(rest)), sample))
        rest = [rest[i] for i in keep]
    return Person(ref, name, tuple(Note(sentence, True) for sentence in head + rest))


def fixture_people(*, sample: int | None = None, seed: int = 7) -> dict[str, Person]:
    rng = random.Random(seed)
    people = {p.id: fixture_person(p.id, p.name, p.persona, sample=sample, rng=rng) for p in MATCH_PERSONAS}
    people.update({d.id: fixture_person(d.id, d.name, d.persona, sample=sample, rng=rng) for d in DECOYS})
    return people


FIXTURE_FRIENDS: dict[str, str] = {p.id: p.friend for p in MATCH_PERSONAS}
FIXTURE_DECOYS: dict[str, str] = {person: decoy.id for decoy in DECOYS for person in decoy.near}


@dataclass(frozen=True)
class Case:
    person: str
    friend: str
    decoy: str | None
    others: tuple[str, ...]


def build_cases(friends: dict[str, str], decoys: dict[str, str], *, seed: int = 7) -> list[Case]:
    """One case per person with a planted friend. The others are the remaining people with a friend
    of their own, in a seeded order so a rerun judges the same candidates."""
    rng = random.Random(seed)
    cases = []
    for person in sorted(friends):
        friend = friends[person]
        others = [other for other in sorted(friends) if other not in (person, friend)]
        rng.shuffle(others)
        cases.append(Case(person, friend, decoys.get(person), tuple(others)))
    return cases


@dataclass(frozen=True)
class Round:
    test: str
    person: str
    candidates: tuple[str, ...]
    best: str | None = None
    friend_rank: int | None = None
    decoy_rank: int | None = None
    decoy_clash: bool = False
    askable: bool = False
    reasons: list[str] = field(default_factory=list)
    why_not: dict[str, str] = field(default_factory=dict)
    clashes: dict[str, str] = field(default_factory=dict)
    pull: dict[str, str] = field(default_factory=dict)
    order: tuple[str, ...] = ()
    # Who the ranking picked before the second look; differs from best when the pick was taken back.
    first_pick: str | None = None
    error: str | None = None


# (person ref, candidate refs) -> the Person, the candidate Persons, and style lines per candidate ref.
Build = Callable[[str, list[str]], tuple[Person, list[Person], dict[str, list[str]]]]


def fixture_build(people: dict[str, Person]) -> Build:
    return lambda person, candidates: (people[person], [people[c] for c in candidates], {})


EVIDENCE = ("all", "no_notes", "notes_only")


def db_build(user_ids: dict[str, str], *, evidence: str = "all") -> Build:
    """Build packs from what is stored, for people named by a short id (persona id -> user id).
    `evidence` leaves a source out to compare them: "no_notes" is vibe lines and memory statements
    (what there was before match notes), "notes_only" is match notes and vibe lines."""
    from agent.matching.choose import Loaded, load_person, notes_toward
    from agent.matching.style import pair_style_lines

    loaded: dict[str, Loaded] = {}

    def get(ref: str) -> Loaded:
        if ref not in loaded:
            loaded[ref] = load_person(user_ids[ref], notes=evidence != "no_notes", statements=evidence != "notes_only")
        return loaded[ref]

    def build(person: str, candidates: list[str]) -> tuple[Person, list[Person], dict[str, list[str]]]:
        own, others = get(person), [get(c) for c in candidates]
        style = {c: pair_style_lines(own.style, other.style, own.name, other.name) for c, other in zip(candidates, others)}
        return (
            Person(person, own.name, notes_toward(own, others)),
            [Person(c, other.name, notes_toward(other, [own])) for c, other in zip(candidates, others)],
            style,
        )

    return build


async def evaluate(
    cases: list[Case],
    build: Build,
    *,
    tests: tuple[str, ...] = TESTS,
    rounds: int = 3,
    model: str | None = None,
    seed: int = 7,
    confirm: bool = True,
    progress: Callable[[Round], None] | None = None,
) -> list[Round]:
    """Every test, `rounds` times each with a different candidate order. Calls run a few at a time."""
    gate = asyncio.Semaphore(PARALLEL_CALLS)
    jobs: list[Awaitable[Round]] = []

    async def one(test: str, case: Case, candidates: tuple[str, ...], call_seed: int) -> Round:
        async with gate:
            try:
                person, people, style = build(case.person, list(candidates))
                choice = await choose_among(person, people, style=style, model=model, rng=random.Random(call_seed), timeout_seconds=TIMEOUT_SECONDS, confirm=confirm)
            except Exception as error:  # a failed call is a result too
                result = Round(test, case.person, candidates, error=type(error).__name__)
            else:
                result = _round(test, case, candidates, choice)
        if progress:
            progress(result)
        return result

    for case_index, case in enumerate(cases):
        decoy = (case.decoy,) if case.decoy else ()
        for round_index in range(rounds):
            call_seed = seed * 1000 + case_index * 10 + round_index
            if "with_friend" in tests:
                jobs.append(one("with_friend", case, (case.friend, *decoy, *case.others[:OTHERS_WITH_FRIEND]), call_seed))
            if "without_friend" in tests:
                jobs.append(one("without_friend", case, (*decoy, *case.others[:OTHERS_WITHOUT_FRIEND]), call_seed))
        if "one_at_a_time" in tests:
            for target in (case.friend, *decoy, *case.others[:2]):
                jobs.append(one("one_at_a_time", case, (target,), seed))
    return list(await asyncio.gather(*jobs))


def _round(test: str, case: Case, candidates: tuple[str, ...], choice: Choice) -> Round:
    return Round(
        test, case.person, candidates, choice.best,
        friend_rank=choice.rank_of(case.friend) if case.friend in candidates else None,
        decoy_rank=choice.rank_of(case.decoy) if case.decoy and case.decoy in candidates else None,
        decoy_clash=bool(case.decoy and case.decoy in choice.clashes),
        askable=choice.askable,
        reasons=[reason["text"] for reason in choice.reasons],
        why_not=dict(choice.why_not), clashes=dict(choice.clashes), pull=dict(choice.pull), order=choice.order, first_pick=choice.first_pick,
    )


def summarise(results: list[Round], cases: list[Case]) -> dict[str, dict[str, int | float]]:
    """Counts per test. Rounds that failed are counted apart and left out of the rest."""
    by_person = {case.person: case for case in cases}
    out: dict[str, dict[str, int | float]] = {}

    ok = [r for r in results if r.test == "with_friend" and not r.error]
    if ok or any(r.test == "with_friend" for r in results):
        ranks = [r.friend_rank for r in ok if r.friend_rank]
        with_decoy = [r for r in ok if r.decoy_rank]
        out["with_friend"] = {
            "rounds": len(ok),
            "errors": sum(1 for r in results if r.test == "with_friend" and r.error),
            "friend_first": sum(1 for r in ok if r.best is not None and r.friend_rank == 1),
            "said_nobody": sum(1 for r in ok if r.best is None),
            "friend_taken_back": sum(1 for r in ok if r.best is None and r.friend_rank == 1 and r.first_pick is not None),
            "friend_rank_mean": round(sum(ranks) / len(ranks), 2) if ranks else 0.0,
            "candidates": max((len(r.candidates) for r in ok), default=0),
            "askable": sum(1 for r in ok if r.askable),
            "decoy_rounds": len(with_decoy),
            "decoy_above_friend": sum(1 for r in with_decoy if r.friend_rank and r.decoy_rank < r.friend_rank),
            "decoy_clash": sum(1 for r in with_decoy if r.decoy_clash),
            "decoy_last": sum(1 for r in with_decoy if r.decoy_rank == len(r.candidates)),
        }

    ok = [r for r in results if r.test == "without_friend" and not r.error]
    if ok or any(r.test == "without_friend" for r in results):
        out["without_friend"] = {
            "rounds": len(ok),
            "errors": sum(1 for r in results if r.test == "without_friend" and r.error),
            "said_nobody": sum(1 for r in ok if r.best is None),
            "taken_back": sum(1 for r in ok if r.best is None and r.first_pick is not None),
            "picked_decoy": sum(1 for r in ok if r.best is not None and r.best == by_person[r.person].decoy),
            "picked_other": sum(1 for r in ok if r.best is not None and r.best != by_person[r.person].decoy),
        }

    ok = [r for r in results if r.test == "one_at_a_time" and not r.error]
    if ok or any(r.test == "one_at_a_time" for r in results):
        def kind(r: Round) -> str:
            case = by_person[r.person]
            return "friend" if r.candidates[0] == case.friend else "decoy" if r.candidates[0] == case.decoy else "other"

        summary: dict[str, int | float] = {"errors": sum(1 for r in results if r.test == "one_at_a_time" and r.error)}
        for name in ("friend", "decoy", "other"):
            group = [r for r in ok if kind(r) == name]
            summary[f"{name}_total"] = len(group)
            summary[f"{name}_approved"] = sum(1 for r in group if r.best is not None)
        out["one_at_a_time"] = summary
    return out


# ---- the two-sided pick (agent.matching.mutual) on seeded people ----

MUTUAL_SETS = ("everyone", "ready_only", "no_friends")


async def evaluate_mutual(user_ids: dict[str, str], friends: dict[str, str], *, rounds: int = 3, model: str | None = None, seed: int = 7, common: bool = True) -> list[dict]:
    """Run the pick the live flow would run, on three sets of the seeded people:

    - everyone: every planted pair is there, so the right answer is exactly those pairs;
    - ready_only: only people the notes rule calls ready, so a friend whose friend is not ready should wait;
    - no_friends: one person from each planted pair, so nobody has a friend there and the right answer is no pair.
    """
    from agent.matching.choose import load_person
    from agent.matching.mutual import mutual_pick
    from agent.matching.notes import match_notes_readiness

    loaded = {ref: load_person(user_id) for ref, user_id in user_ids.items()}
    # mutual_pick names people by their Loaded.ref, which is the user id; work in persona ids instead.
    people = {ref: type(person)(ref, person.name, person.lines, person.memories, person.vectors, person.style) for ref, person in loaded.items()}
    if common:
        # As the live pick does: what is ordinary is judged over the whole group.
        from agent.matching.common import mark_common

        people = await mark_common(people)
    ready = {ref for ref, user_id in user_ids.items() if match_notes_readiness(user_id)["ready"]}
    sets = {
        "everyone": sorted(people),
        "ready_only": sorted(ready),
        "no_friends": sorted(ref for ref in people if ref < friends.get(ref, "")),
    }
    planted = {frozenset((ref, friend)) for ref, friend in friends.items()}
    out = []
    for name in MUTUAL_SETS:
        members = sets[name]
        possible = sorted(tuple(sorted(pair)) for pair in planted if pair <= set(members))
        for round_index in range(rounds):
            result = await mutual_pick({ref: people[ref] for ref in members}, model=model, seed=seed * 100 + round_index, timeout_seconds=TIMEOUT_SECONDS)
            made = [(pair.user_a, pair.user_b, pair.kind) for pair in result.pairs]
            out.append({
                "set": name, "members": members, "possible": possible,
                "right": [pair for pair in made if frozenset(pair[:2]) in planted],
                "wrong": [pair for pair in made if frozenset(pair[:2]) not in planted],
                "waiting": list(result.waiting), "not_taken": list(result.not_taken), "errors": dict(result.errors),
                "wanted": {ref: look.best for ref, look in sorted(result.looks.items())},
                "reasons": {f"{pair.user_a}+{pair.user_b}": [reason["text"] for reason in pair.check["reasons"]] for pair in result.pairs},
            })
    return out


def report_mutual(rounds: list[dict], *, show_reasons: bool = False) -> str:
    lines = ["## The two-sided pick", "", "| people | planted pairs possible | right pairs made | wrong pairs made | rounds with no wrong pair |", "|---|---|---|---|---|"]
    for name in MUTUAL_SETS:
        group = [r for r in rounds if r["set"] == name]
        if not group:
            continue
        possible = sum(len(r["possible"]) for r in group)
        lines.append(f"| {name} ({len(group[0]['members'])}) | {possible} | {sum(len(r['right']) for r in group)} | {sum(len(r['wrong']) for r in group)} | {sum(1 for r in group if not r['wrong'])}/{len(group)} |")
    lines += ["", "| people | pairs made | waiting | each person's own first pick | not taken |", "|---|---|---|---|---|"]
    for r in rounds:
        made = ", ".join(f"{a}+{b} ({kind})" for a, b, kind in r["right"] + r["wrong"]) or "none"
        wanted = ", ".join(f"{ref}→{best or 'nobody'}" for ref, best in r["wanted"].items())
        not_taken = "; ".join(f"{a}→{b}: {why}" for a, b, why in r["not_taken"]) or "-"
        lines.append(f"| {r['set']} | {made} | {', '.join(r['waiting']) or '-'} | {wanted} | {not_taken} |")
    if show_reasons:
        lines.append("")
        for r in rounds:
            for pair, reasons in r["reasons"].items():
                lines += [f"- {r['set']} · {pair}: {text}" for text in reasons]
    return "\n".join(lines)


def report(results: list[Round], cases: list[Case], *, show_reasons: bool = False) -> str:
    """Markdown. Reasons and why-nots only when asked: with real people they quote what was said."""
    summary = summarise(results, cases)
    lines: list[str] = []
    if "with_friend" in summary:
        s = summary["with_friend"]
        n = s["rounds"]
        lines += [
            "## With the friend among the candidates",
            "",
            f"{s['candidates']} candidates a round, so a judge that guesses puts the friend first 1 time in {s['candidates']}.",
            "",
            "| measure | result |", "|---|---|",
            f"| friend chosen as best | {s['friend_first']}/{n} |",
            f"| said nobody | {s['said_nobody']}/{n} |",
            f"| friend ranked first, then taken back by the second look | {s['friend_taken_back']}/{n} |",
            f"| friend's average place (1 is best) | {s['friend_rank_mean']} |",
            f"| best had a reason that may be told | {s['askable']}/{n} |",
        ]
        if s["decoy_rounds"]:
            lines += [
                f"| decoy placed above the friend | {s['decoy_above_friend']}/{s['decoy_rounds']} |",
                f"| decoy marked as a clash | {s['decoy_clash']}/{s['decoy_rounds']} |",
                f"| decoy placed last | {s['decoy_last']}/{s['decoy_rounds']} |",
            ]
        lines += [f"| failed calls | {s['errors']} |", ""]
    if "without_friend" in summary:
        s = summary["without_friend"]
        n = s["rounds"]
        lines += [
            "## Without the friend", "",
            "Nobody here is a planted match. \"Nobody\" is the right answer; the decoy is the worst one.", "",
            "| measure | result |", "|---|---|",
            f"| said nobody | {s['said_nobody']}/{n} |",
            f"| of those, a pick the second look took back | {s['taken_back']} |",
            f"| chose the decoy | {s['picked_decoy']}/{n} |",
            f"| chose someone else | {s['picked_other']}/{n} |",
            f"| failed calls | {s['errors']} |", "",
        ]
    if "one_at_a_time" in summary:
        s = summary["one_at_a_time"]
        lines += [
            "## One candidate at a time", "",
            "The way judges v1 and v2 are asked: approve or reject a single person.", "",
            "| candidate | approved |", "|---|---|",
            f"| the friend | {s['friend_approved']}/{s['friend_total']} |",
            f"| the decoy | {s['decoy_approved']}/{s['decoy_total']} |",
            f"| someone else | {s['other_approved']}/{s['other_total']} |",
            f"| failed calls | {s['errors']} |", "",
        ]
    lines += ["## Every round", "", "| test | person | best | friend's place | decoy's place | decoy clash | pull, in the judge's order |", "|---|---|---|---|---|---|---|"]
    for r in results:
        best = r.error or r.best or "nobody"
        pulls = ", ".join(f"{who} {r.pull.get(who, '?')}" for who in (r.order or r.candidates))
        lines.append(f"| {r.test} | {r.person} | {best} | {r.friend_rank or '-'} | {r.decoy_rank or '-'} | {'yes' if r.decoy_clash else '-'} | {pulls} |")
    if show_reasons:
        lines.append("")
        for r in results:
            head = f"{r.test} · {r.person} -> {r.best or 'nobody'}"
            lines += [f"- {head}: {reason}" for reason in r.reasons]
            lines += [f"- {head} · clash with {who}: {note}" for who, note in r.clashes.items()]
            lines += [f"- {head} · not {who}: {note}" for who, note in r.why_not.items()]
    return "\n".join(lines)


__all__ = [
    "DECOYS", "EVIDENCE", "FIXTURE_DECOYS", "FIXTURE_FRIENDS", "TESTS", "Case", "Decoy", "Round",
    "MUTUAL_SETS", "build_cases", "db_build", "evaluate", "evaluate_mutual", "report_mutual", "fixture_build", "fixture_people", "fixture_person", "report", "summarise", "third_person",
]
