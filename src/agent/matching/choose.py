"""Judge v3: for one person, which of several candidates is most worth an introduction, if any.

Judges v1 and v2 (agent.matching.compatibility) look at one pair and say yes, maybe or no. Asked
that way a model finds something in common for almost every pair, so it cannot tell pairs apart.
This judge is given one person and up to five candidates and has to rank them against each other,
and "nobody" is an allowed answer.

It reads notes, not a fixed card: every vibe line with proof and the person's own statements from
memory, numbered. What leaves an account is what touchpoints already allow (active, standard
sensitivity, not a how-to-talk rule, names taken out). A reason names one note from each side;
code keeps it only when both notes may back a reason and the text uses words from both. A
candidate with a clash is never best, and the first of the ranking is best only when a second call
that sees that candidate alone agrees. Nothing here writes to a pair or asks anyone: v2 still runs
the live flow until the evaluation (agent.evals.matching.choose_eval) says this one is better.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field, replace
from typing import Any

from agent.memory_engine.memories.ranking import embedding_similarity
from agent.shared.vibe import PRIVATE_AREA_IDS, VIBE_AREA_IDS, line_evidence, line_text

from .compatibility import MAX_REASONS, _clean, _content_words, _first_name
from .touchpoints import memory_text, reason_allowed, shareable

CHOOSE_VERSION = 3
MAX_CANDIDATES = 5
# Memory statements per person in one pack, on top of their vibe lines.
MAX_STATEMENTS = 20
PULLS = ("strong", "some", "none")
# How many candidates the ranking called strong get a second look before the answer is "nobody".
MAX_SECOND_LOOKS = 3

MATCH_CHOOSE_SYSTEM_PROMPT = """You help a companion decide which one person, if any, to introduce to someone it knows well.

Input JSON:
- "person": {"name", "notes": [{"id", "text", "reason_ok", "area"?}]}: what the companion knows about
  them, from what they said over weeks. A note with "area" is a summary line of that kind (loves,
  humour, wants, cannot_stand, interests and so on); the others are single things they said. "[name]" stands for a
  name taken out.
- "candidates": [{"key", "name", "notes": [...], "style": [...]}]: other people, with the same kind of
  notes. "style" lines compare how that candidate and the person write (language, hours, length).

Compare the candidates with each other, for this person: who would the person most enjoy talking
to, and who would enjoy talking to them back?

What counts: the same kind of humour; an interest either would talk about for an hour; wanting the
same thing from a friend; being in the same moment of life, or one having been through what the other
is in; one needing what the other gives; a way of keeping in touch that fits. What one cannot stand
and the other does is a clash, and a clash outweighs shared interests.
What does not count: anything true of most candidates (same city, same age, both new in town, both in
tech), and being free at the same hours, which only makes talking easier. If a reason would fit several
candidates, it is not a reason for this one.

Return JSON only:
{"pull": {"<key>": "strong" | "some" | "none"},
 "order": [every candidate key, the one most worth introducing first],
 "best": "<the first key in order>" | null,
 "reasons": [{"mine": "<a person note id>", "theirs": "<a note id of the best candidate>", "text": "<one sentence, both first names, specific>"}],
 "difference": {"mine": "<id>", "theirs": "<id>", "text": "<one difference they could live with, one sentence>"} | null,
 "icebreaker": "<one line either could open with, from the reasons>" | null,
 "chemistry": "<one sentence: would a conversation between them flow, and who would carry it>" | null,
 "why_not": {"<key>": "<one sentence>"},
 "clash": [{"who": "<key>", "mine": "<a person note id>", "theirs": "<a note id of that candidate>", "note": "<what one cannot stand that the other does, one sentence>"}]}

Rules: give every candidate a "pull" before you order them. "strong": at least two different things
from the list of what counts hold for this pair in particular, and nothing in their notes works against
it. "some": one such thing, or more than one but their notes also pull apart (a different rhythm, a
different idea of what a friend is for, a different kind of humour). "none": nothing in particular, or
a clash. Ask of each: a week after the introduction, would both be glad of it?
"best" is the first key only when its pull is strong, and null otherwise. Null is a normal answer:
the least bad of a weak set is not a match, and an introduction with a weak reason is worse than
none. Reasons, difference and icebreaker
are about the best candidate only: at most three reasons, each from a different pair of notes, only
notes with reason_ok true, and the text must use words from both notes, with no new facts. "why_not"
has one entry for every candidate that is not best. A clash may name any note, and a candidate with
a clash is never best. No scores, no flattery."""


@dataclass(frozen=True)
class Note:
    """One thing known about a person: a vibe line (area set) or something they said."""

    text: str
    reason_ok: bool
    area: str | None = None
    memory_id: str | None = None
    # Set for a match note (agent.matching.notes); area then holds its kind.
    note_id: str | None = None


@dataclass(frozen=True)
class Person:
    ref: str
    name: str
    notes: tuple[Note, ...]


@dataclass(frozen=True)
class Choice:
    """The judge's answer after the checks, with candidates named by their own refs."""

    person: str
    order: tuple[str, ...]
    best: str | None
    reasons: list[dict[str, str]] = field(default_factory=list)
    difference: dict[str, str] | None = None
    icebreaker: str | None = None
    chemistry: str | None = None
    why_not: dict[str, str] = field(default_factory=dict)
    clashes: dict[str, str] = field(default_factory=dict)
    # strong, some or none per candidate: how much there is between them and the person.
    pull: dict[str, str] = field(default_factory=dict)
    # False when the model left candidates out of its order; code put them at the end.
    complete: bool = True
    # Who the ranking put first with a strong pull, before the second look. Differs from best when
    # the second look took the pick back.
    first_pick: str | None = None
    version: int = CHOOSE_VERSION

    @property
    def askable(self) -> bool:
        """There is a best candidate and at least one reason that may be told to both."""
        return self.best is not None and bool(self.reasons)

    def rank_of(self, ref: str) -> int | None:
        return self.order.index(ref) + 1 if ref in self.order else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "person": self.person, "order": list(self.order), "best": self.best, "reasons": list(self.reasons),
            "difference": self.difference, "icebreaker": self.icebreaker, "chemistry": self.chemistry,
            "why_not": dict(self.why_not), "clashes": dict(self.clashes), "pull": dict(self.pull), "complete": self.complete, "first_pick": self.first_pick, "version": self.version,
        }


def choose_pack(person: Person, candidates: list[Person], *, style: dict[str, list[str]] | None = None) -> tuple[str, dict[str, Any]]:
    """The JSON the judge reads, and what code needs to check the answer: every note by its id and
    which ref each key stands for. Candidates get neutral keys in the order given."""

    notes: dict[str, Note] = {}

    def numbered(prefix: str, items: tuple[Note, ...]) -> list[dict[str, Any]]:
        out = []
        for n, note in enumerate(items, start=1):
            note_id = f"{prefix}:{n}"
            notes[note_id] = note
            item: dict[str, Any] = {"id": note_id, "text": note.text, "reason_ok": note.reason_ok}
            if note.area:
                item["area"] = note.area
            out.append(item)
        return out

    keys: dict[str, str] = {}
    packed = []
    for n, candidate in enumerate(candidates, start=1):
        key = f"c{n}"
        keys[key] = candidate.ref
        packed.append({"key": key, "name": candidate.name, "notes": numbered(key, candidate.notes), "style": list((style or {}).get(candidate.ref) or [])})
    pack = {"person": {"name": person.name, "notes": numbered("p", person.notes)}, "candidates": packed}
    return json.dumps(pack, ensure_ascii=False), {"notes": notes, "keys": keys}


def validate_choice(raw: Any, index: dict[str, Any]) -> dict[str, Any]:
    """Keep only what the pack supports. The order is made whole (unknown keys dropped, missing ones
    put last, sorted so it agrees with the pull levels), candidates with a clash go to the end and
    cannot be best, the first is best only when the judge called its pull strong (a missing pull
    counts as none), and a reason survives only
    when it names one of the person's notes and one of the best candidate's, both allowed to back a
    reason, with words from both. Keys, not refs: the caller maps them back."""
    data = raw if isinstance(raw, dict) else {}
    notes: dict[str, Note] = index["notes"]
    keys = list(index["keys"])

    clashes: dict[str, str] = {}
    for item in data.get("clash") or []:
        if not isinstance(item, dict):
            continue
        who, note = str(item.get("who") or ""), _clean(item.get("note"))
        mine, theirs = str(item.get("mine") or ""), str(item.get("theirs") or "")
        # A clash has to point at something each of them said; a bare claim does not count.
        if who in keys and note and who not in clashes and mine.startswith("p:") and mine in notes and theirs.startswith(f"{who}:") and theirs in notes:
            clashes[who] = note

    given = [str(key) for key in data.get("order") or [] if isinstance(key, str)]
    order = list(dict.fromkeys(key for key in given if key in keys))
    complete = len(order) == len(keys)
    order += [key for key in keys if key not in order]

    pull_raw = data.get("pull") if isinstance(data.get("pull"), dict) else {}
    pull = {key: (str(pull_raw.get(key) or "").lower() if str(pull_raw.get(key) or "").lower() in PULLS else "none") for key in keys}
    pull.update({key: "none" for key in clashes})
    # The order has to agree with the pull the judge itself gave: strong before some before none,
    # the judge's own order inside each, and clashes last of all.
    order.sort(key=lambda key: (key in clashes, PULLS.index(pull[key])))

    best = data.get("best")
    best = order[0] if isinstance(best, str) and best in keys and order and pull[order[0]] == "strong" else None

    reasons: list[dict[str, str]] = []
    difference = None
    if best is not None:
        used_mine: set[str] = set()
        used_theirs: set[str] = set()
        for item in data.get("reasons") or []:
            checked = _pair_of_notes(item, best, notes, need_reason_ok=True)
            if checked is None or checked["mine"] in used_mine or checked["theirs"] in used_theirs:
                continue
            if not _uses_both(checked["text"], notes[checked["mine"]].text, notes[checked["theirs"]].text):
                continue
            used_mine.add(checked["mine"])
            used_theirs.add(checked["theirs"])
            reasons.append(checked)
            if len(reasons) == MAX_REASONS:
                break
        difference = _pair_of_notes(data.get("difference"), best, notes, need_reason_ok=True)

    why_not_raw = data.get("why_not") if isinstance(data.get("why_not"), dict) else {}
    why_not = {key: _clean(text) for key, text in why_not_raw.items() if key in keys and key != best and _clean(text)}
    return {
        "order": order, "best": best, "reasons": reasons, "difference": difference,
        "icebreaker": (_clean(data.get("icebreaker")) or None) if best else None,
        "chemistry": (_clean(data.get("chemistry")) or None) if best else None,
        "why_not": why_not, "clashes": clashes, "pull": pull, "complete": complete,
    }


async def choose_among(
    person: Person,
    candidates: list[Person],
    *,
    style: dict[str, list[str]] | None = None,
    model: str | None = None,
    rng: random.Random | None = None,
    timeout_seconds: float | None = 60,
    confirm: bool = True,
) -> Choice:
    """Rank the candidates, then look at the first one alone.

    Ranking is what a model does well with several people side by side, but it grades on a curve:
    the least bad of a weak set comes out "strong". Asked about one person alone it is strict. So
    the ranking picks, and a second call with only that candidate has to call the pull strong too.
    If it does not, the next one the ranking called strong is looked at, and with none left there
    is no best. Candidates go in shuffled order: a ranking judge leans towards whoever
    comes first, so the caller's order must not leak into the answer.
    """
    if not candidates:
        return Choice(person.ref, (), None)
    shuffled = list(candidates[:MAX_CANDIDATES])
    (rng or random).shuffle(shuffled)
    ranked = await _ask(person, shuffled, style, model, timeout_seconds)
    if not confirm or ranked.best is None or len(shuffled) == 1:
        return ranked
    pull, why_not, clashes = dict(ranked.pull), dict(ranked.why_not), dict(ranked.clashes)
    # Every candidate the ranking called strong gets its second look, in the ranking's order, until
    # one holds.
    for ref in [ref for ref in ranked.order if ranked.pull.get(ref) == "strong"][:MAX_SECOND_LOOKS]:
        alone = await _ask(person, [c for c in shuffled if c.ref == ref], style, model, timeout_seconds)
        if alone.best is not None:
            # Confirmed: the second look wrote about this one pair only, so its words are the better ones.
            kept = ref == ranked.best
            return replace(
                ranked, best=ref, order=_by_pull(ranked.order, pull, clashes), pull=pull, why_not={k: v for k, v in why_not.items() if k != ref}, clashes=clashes,
                reasons=alone.reasons or (ranked.reasons if kept else []), difference=alone.difference or (ranked.difference if kept else None),
                icebreaker=alone.icebreaker or (ranked.icebreaker if kept else None), chemistry=alone.chemistry or (ranked.chemistry if kept else None),
                first_pick=ranked.best,
            )
        # Taken back: its pull is what the second look said, never strong.
        level = alone.pull.get(ref, "some")
        pull[ref] = "some" if level == "strong" else level
        why_not.update(alone.why_not)
        clashes.update(alone.clashes)
    return replace(
        ranked, best=None, order=_by_pull(ranked.order, pull, clashes), pull=pull, why_not=why_not, clashes=clashes,
        reasons=[], difference=None, icebreaker=None, chemistry=None, first_pick=ranked.best,
    )


def _by_pull(order: tuple[str, ...], pull: dict[str, str], clashes: dict[str, str]) -> tuple[str, ...]:
    """Strong before some before none, clashes last, the given order inside each."""
    return tuple(sorted(order, key=lambda ref: (ref in clashes, PULLS.index(pull.get(ref, "none")))))


async def _ask(person: Person, candidates: list[Person], style: dict[str, list[str]] | None, model: str | None, timeout_seconds: float | None) -> Choice:
    """One judge call on the candidates in the order given, checked, with keys turned back into refs."""
    from agent.providers import choose_match

    pack, index = choose_pack(person, candidates, style=style)
    raw = await choose_match(pack, conversation_id=f"match-choose:{person.ref}", model=model, timeout_seconds=timeout_seconds)
    checked = validate_choice(raw, index)
    ref = index["keys"].get

    def sourced(item: dict[str, str] | None) -> dict[str, str] | None:
        """Pack ids mean nothing outside this call: name each side by its area or memory instead."""
        return {"text": item["text"], "mine": _source(index["notes"][item["mine"]]), "theirs": _source(index["notes"][item["theirs"]])} if item else None

    best = ref(checked["best"]) if checked["best"] else None
    return Choice(
        person.ref,
        tuple(ref(key) for key in checked["order"]),
        best,
        [sourced(reason) for reason in checked["reasons"]], sourced(checked["difference"]), checked["icebreaker"], checked["chemistry"],
        {ref(key): text for key, text in checked["why_not"].items()},
        {ref(key): text for key, text in checked["clashes"].items()},
        {ref(key): level for key, level in checked["pull"].items()},
        complete=checked["complete"],
        first_pick=best,
    )


# ---- what is stored about a user, as notes ----


@dataclass(frozen=True)
class Loaded:
    """One user's vibe lines and shareable memories with their vectors, before any pack is cut."""

    ref: str
    name: str
    lines: tuple[Note, ...]
    memories: tuple[dict[str, Any], ...]
    vectors: dict[str, dict[str, Any]]
    style: dict[str, Any]


def load_person(user_id: str, *, notes: bool = True, statements: bool = True) -> Loaded:
    """What is stored about a user, as notes for a pack: their match notes first (who they are,
    several per kind), then vibe lines, then memory statements. `notes` and `statements` switch a
    source off, for the evaluation that compares them."""
    from storage import get_match_notes, get_user_profile, get_user_style, get_vibe_card, list_agent_memories, private_matching_allowed
    from storage.memory_embeddings import list_agent_memory_embeddings

    from .notes import NOTE_KINDS, PRIVATE_KINDS, REASON_KINDS

    card = get_vibe_card(user_id)
    areas = card.get("areas") or {}
    private_ok = private_matching_allowed(card)
    stored = (get_match_notes(user_id) or {}).get("notes") or [] if notes else []
    lines = tuple(
        Note(str(note["text"]), note["kind"] in REASON_KINDS, area=note["kind"], note_id=str(note.get("id") or ""))
        for note in stored
        if isinstance(note, dict) and note.get("kind") in NOTE_KINDS and note.get("text") and (private_ok or note["kind"] not in PRIVATE_KINDS)
    ) + tuple(
        Note(line_text(areas[area_id]), area_id not in PRIVATE_AREA_IDS, area=area_id)
        for area_id in VIBE_AREA_IDS
        if line_text(areas.get(area_id)) and line_evidence(areas.get(area_id)) and (private_ok or area_id not in PRIVATE_AREA_IDS)
    )
    memories = tuple(memory for memory in list_agent_memories(user_id) if shareable(memory)) if statements else ()
    vectors = {str(item["memory_id"]): item for item in list_agent_memory_embeddings(user_id, [str(m["id"]) for m in memories])} if memories else {}
    return Loaded(user_id, _first_name(get_user_profile(user_id), "Someone"), lines, memories, vectors, get_user_style(user_id) or {})


def notes_toward(own: Loaded, others: list[Loaded], *, limit: int = MAX_STATEMENTS) -> tuple[Note, ...]:
    """A person's notes for a pack with these other people: every vibe line, then statements. With
    more statements than fit, half the room goes to the ones closest in meaning to anything the
    others said (that is where reasons and clashes are), the rest to the most important and newest."""
    memories = list(own.memories)
    if len(memories) > limit:
        other_vectors = [vector for other in others for vector in other.vectors.values()]

        def closeness(memory: dict[str, Any]) -> float:
            vector = own.vectors.get(str(memory["id"]))
            scores = [score for other in other_vectors if (score := embedding_similarity(vector, other)) is not None] if vector else []
            return max(scores, default=0.0)

        by_closeness = sorted(memories, key=closeness, reverse=True)[: limit // 2]
        taken = {str(memory["id"]) for memory in by_closeness}
        rest = sorted(
            (memory for memory in memories if str(memory["id"]) not in taken),
            key=lambda memory: (float(memory.get("importance") or 0), str(memory.get("updated_at") or memory.get("created_at") or "")),
            reverse=True,
        )
        memories = by_closeness + rest[: limit - len(by_closeness)]
    return own.lines + tuple(Note(memory_text(memory), reason_allowed(memory), memory_id=str(memory["id"])) for memory in memories)


async def choose_for(user_id: str, candidate_ids: list[str], *, model: str | None = None, rng: random.Random | None = None) -> Choice:
    """Load what is stored about the user and up to five candidates and ask the judge."""
    from .style import pair_style_lines

    person = load_person(user_id)
    candidates = [load_person(candidate_id) for candidate_id in candidate_ids[:MAX_CANDIDATES]]
    style = {candidate.ref: pair_style_lines(person.style, candidate.style, person.name, candidate.name) for candidate in candidates}
    return await choose_among(
        Person(person.ref, person.name, notes_toward(person, candidates)),
        [Person(candidate.ref, candidate.name, notes_toward(candidate, [person])) for candidate in candidates],
        style=style, model=model, rng=rng,
    )


def _pair_of_notes(item: Any, best: str, notes: dict[str, Note], *, need_reason_ok: bool) -> dict[str, str] | None:
    """{"mine", "theirs", "text"} when it names one of the person's notes and one of the best
    candidate's, both allowed; else None."""
    if not isinstance(item, dict):
        return None
    mine, theirs, text = str(item.get("mine") or ""), str(item.get("theirs") or ""), _clean(item.get("text"))
    if not (text and mine.startswith("p:") and theirs.startswith(f"{best}:") and mine in notes and theirs in notes):
        return None
    if need_reason_ok and not (notes[mine].reason_ok and notes[theirs].reason_ok):
        return None
    return {"mine": mine, "theirs": theirs, "text": text}


def _source(note: Note) -> str:
    if note.note_id:
        return f"note:{note.note_id}"
    return f"area:{note.area}" if note.area else f"memory:{note.memory_id}" if note.memory_id else "note"


def _uses_both(text: str, mine: str, theirs: str) -> bool:
    """The sentence takes at least one content word from each person's note, so it is about both
    of them and not a line that only one side said."""
    words = _content_words(text)
    return bool(words & _content_words(mine)) and bool(words & _content_words(theirs))


__all__ = [
    "CHOOSE_VERSION",
    "MATCH_CHOOSE_SYSTEM_PROMPT",
    "MAX_CANDIDATES",
    "MAX_STATEMENTS",
    "Choice",
    "Loaded",
    "Note",
    "Person",
    "choose_among",
    "choose_for",
    "choose_pack",
    "load_person",
    "notes_toward",
    "validate_choice",
]
