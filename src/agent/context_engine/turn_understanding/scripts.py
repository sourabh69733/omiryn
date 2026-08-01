from __future__ import annotations

import unicodedata

from agent.context_engine.turn_understanding.contract import LanguageProfile


SCRIPT_RANGES: tuple[tuple[str, tuple[tuple[int, int], ...]], ...] = (
    ("Latn", ((0x0041, 0x007A), (0x00C0, 0x024F), (0x1E00, 0x1EFF))),
    ("Deva", ((0x0900, 0x097F), (0xA8E0, 0xA8FF))),
    ("Beng", ((0x0980, 0x09FF),)),
    ("Guru", ((0x0A00, 0x0A7F),)),
    ("Gujr", ((0x0A80, 0x0AFF),)),
    ("Orya", ((0x0B00, 0x0B7F),)),
    ("Taml", ((0x0B80, 0x0BFF),)),
    ("Telu", ((0x0C00, 0x0C7F),)),
    ("Knda", ((0x0C80, 0x0CFF),)),
    ("Mlym", ((0x0D00, 0x0D7F),)),
    (
        "Arab",
        (
            (0x0600, 0x06FF),
            (0x0750, 0x077F),
            (0x08A0, 0x08FF),
            (0xFB50, 0xFDFF),
            (0xFE70, 0xFEFF),
        ),
    ),
)


def detect_language_profile(text: str) -> LanguageProfile:
    counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    letter_index = 0
    for character in text:
        if not unicodedata.category(character).startswith("L"):
            continue
        script = _script_for_character(character)
        if script not in first_seen:
            first_seen[script] = letter_index
        counts[script] = counts.get(script, 0) + 1
        letter_index += 1

    if not counts:
        return LanguageProfile()

    ordered = tuple(
        sorted(
            counts,
            key=lambda script: (-counts[script], first_seen[script]),
        )
    )
    return LanguageProfile(
        scripts=ordered,
        primary_script=ordered[0],
        script_counts=tuple((script, counts[script]) for script in ordered),
        is_mixed_script=len(ordered) > 1,
        has_letters=True,
    )


def _script_for_character(character: str) -> str:
    codepoint = ord(character)
    for script, ranges in SCRIPT_RANGES:
        if any(start <= codepoint <= end for start, end in ranges):
            return script
    return "Other"
