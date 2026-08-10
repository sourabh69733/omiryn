from __future__ import annotations

from typing import Final

DEVANAGARI_START: Final[int] = 0x0900
DEVANAGARI_END: Final[int] = 0x097F
VIRAMA: Final[str] = "\u094d"
NUKTA: Final[str] = "\u093c"

INDEPENDENT_VOWELS: Final[dict[str, str]] = {
    "\u0905": "a",
    "\u0906": "aa",
    "\u0907": "i",
    "\u0908": "ee",
    "\u0909": "u",
    "\u090a": "oo",
    "\u090f": "e",
    "\u0910": "ai",
    "\u0913": "o",
    "\u0914": "au",
}

VOWEL_MARKS: Final[dict[str, str]] = {
    "\u093e": "a",
    "\u093f": "i",
    "\u0940": "ee",
    "\u0941": "u",
    "\u0942": "oo",
    "\u0947": "e",
    "\u0948": "ai",
    "\u094b": "o",
    "\u094c": "au",
    "\u0943": "ri",
}

CONSONANTS: Final[dict[str, str]] = {
    "\u0915": "k",
    "\u0916": "kh",
    "\u0917": "g",
    "\u0918": "gh",
    "\u091a": "ch",
    "\u091b": "chh",
    "\u091c": "j",
    "\u091d": "jh",
    "\u091f": "t",
    "\u0920": "th",
    "\u0921": "d",
    "\u0922": "dh",
    "\u0923": "n",
    "\u0924": "t",
    "\u0925": "th",
    "\u0926": "d",
    "\u0927": "dh",
    "\u0928": "n",
    "\u092a": "p",
    "\u092b": "ph",
    "\u092c": "b",
    "\u092d": "bh",
    "\u092e": "m",
    "\u092f": "y",
    "\u0930": "r",
    "\u0932": "l",
    "\u0935": "v",
    "\u0936": "sh",
    "\u0937": "sh",
    "\u0938": "s",
    "\u0939": "h",
}

NUKTA_CONSONANTS: Final[dict[str, str]] = {
    "\u0915": "q",
    "\u0916": "kh",
    "\u0917": "gh",
    "\u091c": "z",
    "\u0921": "d",
    "\u0922": "dh",
    "\u092b": "f",
}

SIGNS: Final[dict[str, str]] = {
    "\u0902": "n",
    "\u0901": "n",
    "\u0903": "h",
    "\u0964": ".",
    "\u0965": ".",
    "\u0966": "0",
    "\u0967": "1",
    "\u0968": "2",
    "\u0969": "3",
    "\u096a": "4",
    "\u096b": "5",
    "\u096c": "6",
    "\u096d": "7",
    "\u096e": "8",
    "\u096f": "9",
}


def normalize_assistant_script(text: str) -> str:
    if not _has_devanagari(text):
        return text
    return _clean_spacing(_transliterate_devanagari(text))


def _has_devanagari(text: str) -> bool:
    return any(DEVANAGARI_START <= ord(character) <= DEVANAGARI_END for character in text)


def _transliterate_devanagari(text: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        next_character = text[index + 1] if index + 1 < len(text) else ""
        if character in INDEPENDENT_VOWELS:
            output.append(INDEPENDENT_VOWELS[character])
        elif character in CONSONANTS:
            base = (
                NUKTA_CONSONANTS.get(character, CONSONANTS[character])
                if next_character == NUKTA
                else CONSONANTS[character]
            )
            output.append(base)
            if next_character == NUKTA:
                index += 1
                next_character = text[index + 1] if index + 1 < len(text) else ""
            if next_character not in VOWEL_MARKS and next_character != VIRAMA:
                output.append("a")
        elif character in VOWEL_MARKS:
            output.append(VOWEL_MARKS[character])
        elif character == VIRAMA or character == NUKTA:
            pass
        elif character in SIGNS:
            output.append(SIGNS[character])
        else:
            output.append(character)
        index += 1
    return "".join(output)


def _clean_spacing(text: str) -> str:
    return (
        " ".join(text.split())
        .replace("ee ", "i ")
        .replace("ee.", "i.")
        .replace(" .", ".")
        .replace(" ,", ",")
        .replace(" ?", "?")
        .replace(" !", "!")
    )
