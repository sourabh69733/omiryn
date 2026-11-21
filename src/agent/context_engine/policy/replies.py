"""Normalizes and splits a model response into safe user-facing chat bubbles."""

from __future__ import annotations

import os
import re
import unicodedata

from agent.context_engine.policy.script import normalize_assistant_script

REPLY_PART_SEPARATOR = "<next_message>"
# Normal replies use 1-3 bubbles by prompt; 7 leaves room for a story or scene told in one go.
MAX_REPLY_PARTS = int(os.getenv("AGENT_MAX_REPLY_PARTS", "7"))
REPLY_PART_WORD_LIMIT = int(os.getenv("AGENT_REPLY_PART_WORD_LIMIT", "35"))
# The most words one reply carries, however the model laid it out. The prompt asks for short
# replies; this only stops a runaway one. Code never decides from the user's words how long a
# reply may be.
MAX_REPLY_WORDS = MAX_REPLY_PARTS * REPLY_PART_WORD_LIMIT
# Starts every per-turn story note, so later steps know this reply is a story.
STORY_NOTE_PREFIX = "Story turn:"


# Models sometimes write the separator as [next_message], </next_message> or <next message>.
_SEPARATOR_VARIANTS = re.compile(r"[<\[]\s*/?\s*next[\s_-]*message\s*/?\s*[>\]]", re.IGNORECASE)


def normalize_part_separators(text: str) -> str:
    """Rewrite separator variants to the canonical <next_message> so none reach the user."""
    return _SEPARATOR_VARIANTS.sub(REPLY_PART_SEPARATOR, text)


# A model's private thinking, when it writes that into the reply itself instead of keeping it apart.
_THINKING_NAMES = r"(?:think|thinking|thought|thoughts|reasoning|reflection|scratchpad)"
_THINKING_BLOCK = re.compile(rf"<\s*{_THINKING_NAMES}\s*>.*?<\s*/\s*{_THINKING_NAMES}\s*>", re.IGNORECASE | re.DOTALL)
_THINKING_OPEN = re.compile(rf"<\s*{_THINKING_NAMES}\s*>", re.IGNORECASE)
_THINKING_CLOSE = re.compile(rf"<\s*/\s*{_THINKING_NAMES}\s*>", re.IGNORECASE)


def without_thinking(text: str) -> str | None:
    """The reply with the model's thinking cut out, or None when the two cannot be told apart.

    A closed <think>...</think> block is cut. With only a closing tag, everything before it is
    thinking. With only an opening tag nothing marks where the reply starts, so the caller must
    treat the whole text as a failed reply, never show it.
    """
    cleaned = _THINKING_BLOCK.sub(" ", text)
    closes = list(_THINKING_CLOSE.finditer(cleaned))
    if closes:
        cleaned = cleaned[closes[-1].end():]
    return None if _THINKING_OPEN.search(cleaned) else cleaned


# Written by the model after the last part of a story; never shown to the user.
STORY_END_MARKER = "<story_end>"
_STORY_END_VARIANTS = re.compile(r"[<\[]\s*/?\s*story[\s_-]*end\s*/?\s*[>\]]", re.IGNORECASE)


def strip_story_end(text: str) -> tuple[str, bool]:
    """Remove the story-end marker (and its variants); report whether it was there."""
    cleaned, count = _STORY_END_VARIANTS.subn("", text)
    return cleaned.strip(), count > 0


# Written by the model at the start of a reply that tells or continues a story; never shown.
# The model decides, so a story is recognised in any language ("ek kahani sunao" included).
STORY_MARKER = "<story>"
_STORY_MARKER_VARIANTS = re.compile(r"[<\[]\s*story\s*[>\]]", re.IGNORECASE)


def has_story_marker(text: str) -> bool:
    return bool(_STORY_MARKER_VARIANTS.search(text))


# Models used to XML-style tags sometimes close the marker; the closing tag is hidden too.
_STORY_CLOSING_TAG = re.compile(r"[<\[]\s*/\s*story\s*[>\]]", re.IGNORECASE)


def strip_story_marker(text: str) -> tuple[str, bool]:
    """Remove the story marker; report whether the model marked the reply as a story."""
    cleaned, count = _STORY_MARKER_VARIANTS.subn("", text)
    # A stray closing tag alone does not mark a story.
    return _STORY_CLOSING_TAG.sub("", cleaned).strip(), count > 0


# Written by the model when the user asks it to talk like a girl, a boy or neutrally again.
_VOICE_MARKER = re.compile(r"[<\[]\s*voice\s*:\s*(neutral|female|male)\s*[>\]]", re.IGNORECASE)


def strip_voice_marker(text: str) -> tuple[str, str | None]:
    """Remove the voice marker; return the voice the user asked for, if any (the last one wins)."""
    found = _VOICE_MARKER.findall(text)
    return _VOICE_MARKER.sub("", text).strip(), (found[-1].lower() if found else None)


# Written by the model as its whole reply when words would add nothing.
_REACTION_MARKER = re.compile(r"[<\[]\s*react\s*:\s*([^<>\[\]]*?)\s*[>\]]", re.IGNORECASE)
_NO_REPLY_MARKER = re.compile(r"[<\[]\s*no_reply\s*[>\]]", re.IGNORECASE)
# One emoji, with room for its skin tone and joiners.
_REACTION_MAX_CHARS = 12


def is_one_emoji(text: str) -> bool:
    """Short, with a symbol in it (or a keycap such as 1️⃣), and no letters or spaces."""
    if not 0 < len(text) <= _REACTION_MAX_CHARS or any(char.isalpha() or char.isspace() for char in text):
        return False
    return "\u20e3" in text or any(unicodedata.category(char) == "So" for char in text)


def strip_quiet_markers(text: str) -> tuple[str, str | None, bool]:
    """Remove the reaction and no-reply markers; return the text, the emoji, and whether the model
    chose to say nothing. A marker with no words and no usable emoji counts as saying nothing."""
    emojis = [found for found in _REACTION_MARKER.findall(text) if is_one_emoji(found)]
    marked = bool(_REACTION_MARKER.search(text) or _NO_REPLY_MARKER.search(text))
    cleaned = _NO_REPLY_MARKER.sub("", _REACTION_MARKER.sub("", text)).strip()
    reaction = emojis[-1] if emojis else None
    return cleaned, reaction, marked and not cleaned and reaction is None


# Written by the model to put a button under its reply that opens a page of the app.
# "<open:privacy>", or the show_app_page tool written out as text instead of called:
# '<show_app_page page="matches"/>'. Either way the user gets the button, never the tag.
_OPEN_MARKER = re.compile(
    r"[<\[]\s*(?:open\s*:\s*([a-z_ -]*?)|show_app_page\b[^<>\[\]]*?page\s*[=:]\s*[\"']?([a-z_-]*)[\"']?[^<>\[\]]*?)\s*/?\s*[>\]]",
    re.IGNORECASE,
)
# The app pages a button may open; anything else is dropped.
APP_PAGES = ("privacy", "memories", "vibe", "matches", "profile")


def strip_open_marker(text: str) -> tuple[str, str | None]:
    """Remove page markers; return the text and the last page the app can open, if any."""
    pages = [(marker or tool).strip().lower() for marker, tool in _OPEN_MARKER.findall(text)]
    known = [page for page in pages if page in APP_PAGES]
    return _OPEN_MARKER.sub("", text).strip(), (known[-1] if known else None)


def keep_open_marker(draft: str, final: str) -> str:
    """A rewrite is a fresh reply and can drop the draft's page button; the model chose it, so it stays."""
    _, page = strip_open_marker(draft)
    if page is None or not final.strip() or strip_open_marker(final)[1] is not None:
        return final
    return f"{final.rstrip()} <open:{page}>"


# Markdown bold. Chat shows plain text, so the stars would reach the user as stars.
_BOLD = re.compile(r"\*\*(\S(?:[^\n]*?\S)?)\*\*")


def tidy_lines(text: str) -> str:
    """The text with the model's own line breaks kept and the rest tidied: spaces squeezed, at most
    one empty line in a row, no markdown bold. Steps and a drafted mail keep their lines this way."""
    plain = _BOLD.sub(r"\1", str(text or "")).replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in plain.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def split_assistant_reply(reply: str, *, user_text: str | None = None) -> list[str]:
    cleaned = tidy_lines(normalize_part_separators(normalize_assistant_script(str(reply or ""))))
    if not cleaned:
        return [""]

    # A reply written as one message is split the same way as an overlong part: the model's words
    # are never dropped for being long (see MAX_REPLY_WORDS for the one outer limit).
    written = [_normalize_chat_bubble(part) for part in cleaned.split(REPLY_PART_SEPARATOR)]
    bubbles = [_normalize_chat_bubble(bubble) for bubble in _as_bubbles([part for part in written if part])]
    return _limit_parts([bubble for bubble in bubbles if bubble], MAX_REPLY_PARTS) or [_normalize_chat_bubble(cleaned)]


def _as_bubbles(parts: list[str]) -> list[str]:
    """The model's parts as chat bubbles. An overlong part is split at sentence ends. When that
    makes more bubbles than one reply may have, the bubbles grow instead, so nothing is lost.

    A part with line breaks in it was laid out by the model (steps, a mail to copy), so it stays
    one bubble whatever its length."""
    limit = REPLY_PART_WORD_LIMIT
    longest = max((len(part.split()) for part in parts if "\n" not in part), default=0)
    if limit <= 0:
        return parts
    while True:
        bubbles = [
            bubble
            for part in parts
            for bubble in ([part] if "\n" in part else _word_limited_parts(part, limit))
        ]
        if len(bubbles) <= MAX_REPLY_PARTS or limit >= longest:
            return bubbles
        limit += REPLY_PART_WORD_LIMIT


_SENTENCE_END = r"(?<=[.!?।])\s+"
# The number of a step in a list the model wrote out, such as "2." or "2)".
_LIST_NUMBER = r"\d{1,2}[.)]"
_HAS_LIST = re.compile(rf"(?:^|\s)1[.)]\s.*\s2[.)]\s")


def sentences(text: str) -> list[str]:
    """The sentences of a reply, in order. In a numbered list each step is its own sentence and its
    number stays with it: a break never falls between "2." and the step it numbers."""
    cleaned = text.strip()
    # Steps written in a row ("1. ... 2. ...") also break before each number.
    breaks = rf"{_SENTENCE_END}|\s+(?={_LIST_NUMBER}\s)" if _HAS_LIST.search(cleaned) else _SENTENCE_END
    found: list[str] = []
    number = ""
    for piece in re.split(breaks, cleaned):
        piece = f"{number} {piece}".strip()
        number = ""
        if re.fullmatch(_LIST_NUMBER, piece):
            number = piece
        elif piece:
            found.append(piece)
    return found + ([number] if number else [])


def sentence_pieces(text: str) -> list[tuple[str, str]]:
    """Each sentence with the gap after it: a space, or the model's line break. Text taken apart
    by sentence goes back together with its lines (see join_pieces)."""
    pieces: list[tuple[str, str]] = []
    lines = re.split(r"(\n+)", text.strip())
    for index in range(0, len(lines), 2):
        found = sentences(lines[index])
        gap = lines[index + 1] if index + 1 < len(lines) else ""
        pieces.extend((sentence, " ") for sentence in found[:-1])
        if found:
            pieces.append((found[-1], gap))
    return pieces


def join_pieces(pieces: list[tuple[str, str]]) -> str:
    return "".join(sentence + gap for sentence, gap in pieces).strip()


def _word_limited_parts(text: str, word_limit: int) -> list[str]:
    """Split an overlong bubble at sentence ends. A sentence longer than a bubble stays whole in a
    bubble of its own: a break in the middle of a sentence reads worse than a long bubble."""
    words = text.split()
    if not words or word_limit <= 0:
        return [text.strip()] if text.strip() else []
    if len(words) <= word_limit:
        return [text.strip()]
    parts: list[str] = []
    current: list[str] = []
    for sentence in sentences(text):
        sentence_words = sentence.split()
        if current and len(current) + len(sentence_words) > word_limit:
            parts.append(" ".join(current))
            current = []
        current.extend(sentence_words)
    if current:
        parts.append(" ".join(current))
    return [part for part in parts if part]


def _limit_parts(parts: list[str], max_parts: int) -> list[str]:
    if max_parts <= 0 or len(parts) <= max_parts:
        return parts
    return parts[:max_parts]


def _strip_wrapping_quotes(text: str) -> str:
    cleaned = text.strip()
    quote_pairs = {
        '"': '"',
        "'": "'",
        "\u201c": "\u201d",
        "\u2018": "\u2019",
    }
    changed = True
    while changed and len(cleaned) >= 2:
        changed = False
        start = cleaned[0]
        end = quote_pairs.get(start)
        if end and cleaned.endswith(end):
            cleaned = cleaned[1:-1].strip()
            changed = True
    return cleaned


def _normalize_chat_bubble(text: str) -> str:
    cleaned = _strip_speaker_label(_strip_time_note(text))
    return _strip_wrapping_quotes(cleaned)


# The history marks when the user wrote, e.g. "(Mon 5 Oct, 7:30 pm)" or "(9:30 pm, 1 hour
# later)" (see agent.shared.timeline.day_notes). A model copying one into its own bubble leaks it.
_TIME_NOTE = re.compile(
    r"^\(\s*(?:[A-Z][a-z]{2}\s+\d{1,2}\s+[A-Z][a-z]{2},\s*)?\d{1,2}:\d{2}\s*[ap]m"
    r"(?:,\s*[^)]*later)?\s*\)\s*",
    re.IGNORECASE,
)


def _strip_time_note(text: str) -> str:
    return _TIME_NOTE.sub("", text.strip(), count=1)


# Who is speaking, when a model writes that at the start of a bubble: its own name ("Omi: hey"), or
# in a story told like a script, a character's name before the quoted line ('Rahul: "..."').
# Any other start that ends in a colon ("Ek catch: ...", "Saturday 9:43 pm") is the reply itself.
# The names are the ones in prompt_engine.modules.identity.
_OWN_LABEL = re.compile(r"^(?:omi|omiryn|annie|kabir|assistant|ai)\s*:\s+", re.IGNORECASE)
_SCRIPT_LABEL = re.compile(r"^[A-Z][a-z]+(?: [A-Z][a-z]+)?\s*:\s*(?=[\"'“‘])")


def _strip_speaker_label(text: str) -> str:
    cleaned = text.strip()
    for label in (_OWN_LABEL, _SCRIPT_LABEL):
        cleaned = label.sub("", cleaned, count=1)
    return cleaned.strip()
