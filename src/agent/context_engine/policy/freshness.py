"""Spots generic filler and self-repetition in a drafted reply.

Detection only: when a draft is stale, the runtime asks the model for one rewrite. No reply
text is produced here, so fixes stay model-written and specific to the conversation.
"""

from __future__ import annotations

import re
from typing import Any

from .replies import REPLY_PART_SEPARATOR
# Lines that fit any message: a seed plus lines learned from real chats. Matched after normalizing.
from .stock_phrases import STOCK_PHRASES

# Replies this short ("haha", "ok sure") are normal to repeat.
_MIN_WORDS_FOR_REPEAT_CHECK = 4
_RECENT_REPLIES = 20
_OPENING_MAX_WORDS = 4
_OPENING_REPEAT_LIMIT = 2  # the same opening already used this many times recently
_NEAR_COPY_SIMILARITY = 0.6
# Same words in a new order ("sham ho gayi, abhi kya kar rahe ho?") is still the same message.
_SAME_WORDS_SIMILARITY = 0.8


def stale_reply_reason(reply: str, previous_replies: list[str]) -> str | None:
    """Why the draft sounds generic or repeated, or None when it is fine."""
    flat = reply.replace(REPLY_PART_SEPARATOR, " ")
    text = _normalize(flat)
    if not text:
        return None
    for phrase in STOCK_PHRASES:
        if phrase in text:
            return f'it uses the stock line "{phrase}", which fits any message'

    words = text.split()
    if len(words) < _MIN_WORDS_FOR_REPEAT_CHECK:
        return None
    earlier_replies = [item for item in previous_replies[-_RECENT_REPLIES:] if item.strip()]
    for earlier in earlier_replies:
        if _copies(reply, earlier):
            return "it nearly repeats a reply you already sent in this chat"
    opening = _opening(flat)
    if opening:
        same_opening = sum(1 for earlier in earlier_replies if _opening(earlier) == opening)
        if same_opening >= _OPENING_REPEAT_LIMIT:
            return f'it opens with "{opening}" again, as {same_opening} recent replies did'
    return None


def question_rule_reason(reply: str, question_limit: int) -> str | None:
    """Why the draft breaks this turn's question limit, or None when it keeps it."""
    questions = len(re.findall(r"\?+", reply.replace(REPLY_PART_SEPARATOR, " ")))
    if questions <= question_limit:
        return None
    if question_limit == 0:
        return "it asks a question, but this reply must not ask any; react or share a thought instead"
    return f"it asks {questions} questions; ask at most {question_limit}"


def trim_questions(reply: str, question_limit: int) -> str:
    """Last resort when a rewrite still breaks the limit: drop question sentences past it.

    Works on whole sentences and bubbles, so nothing is cut mid-sentence. The questions that say
    the most are kept. A reply is never emptied: if only questions remain, the longest is kept.
    """
    bubbles = [
        [sentence for sentence in re.split(r"(?<=[.!?\u0964])\s+", bubble.strip()) if sentence]
        for bubble in reply.split(REPLY_PART_SEPARATOR)
    ]
    questions = [sentence for bubble in bubbles for sentence in bubble if "?" in sentence]
    # Keep the questions that carry the most; a bare echo ("Kuch bhi?") goes first.
    keep = set(sorted(questions, key=lambda sentence: -len(sentence.split()))[:question_limit])
    kept_bubbles: list[str] = []
    for bubble in bubbles:
        kept: list[str] = []
        for index, sentence in enumerate(bubble):
            if "?" in sentence and sentence not in keep:
                continue
            following = bubble[index + 1] if index + 1 < len(bubble) else None
            dropped_next = following is not None and "?" in following and following not in keep
            # A lead-in ("maine socha...") whose follow-up was dropped would hang unfinished.
            if dropped_next and sentence.rstrip().endswith(("...", "\u2026", ":")):
                continue
            kept.append(sentence)
        if kept:
            kept_bubbles.append(" ".join(kept))
    if not kept_bubbles:
        return max(questions, key=lambda sentence: len(sentence.split())) if questions else reply
    return REPLY_PART_SEPARATOR.join(kept_bubbles)


def recent_assistant_replies(messages: list[dict[str, Any]]) -> list[str]:
    return [
        str(message.get("content") or "")
        for message in messages
        if message.get("role") == "assistant"
    ][-_RECENT_REPLIES:]


def without_copied_replies(messages: list[dict[str, Any]], draft: str) -> list[dict[str, Any]]:
    """Chat history for a rewrite, minus the earlier replies the draft copied or opened like.

    A copied reply left in the history pulls the rewrite straight back to it (seen live: a
    greeting copied word for word on every "hi"), so the rewrite does not see it.
    """
    opening = _opening(draft.replace(REPLY_PART_SEPARATOR, " "))
    return [
        message
        for message in messages
        if message.get("role") != "assistant"
        or not (
            _copies(draft, str(message.get("content") or ""))
            or (opening and _opening(str(message.get("content") or "")) == opening)
        )
    ]


def rewrite_instruction(draft: str, reason: str, *, quote_draft: bool = True, keep_length: bool = True) -> str:
    """The last message the model reads for the single rewrite attempt.

    A draft that copied an earlier reply is not quoted: the model copies the quote back. When the
    draft broke how the user asked to be talked to, the length may be the very thing to change.
    """
    said = f'your draft reply was "{draft.strip()[:400]}". It' if quote_draft else "your draft"
    keep = (
        "Keep the same language, length and format rules."
        if keep_length
        else "Keep the same language; follow what the user asked, even when it changes the length or format."
    )
    return (
        f"Rewrite needed: {said} needs a rewrite because {reason}. "
        "Write a different reply that responds specifically to the user's latest message, "
        f"using what they actually said. {keep}"
    )


def _copies(draft: str, earlier: str) -> bool:
    """The draft, or one of its bubbles, nearly copies the earlier reply or one of its bubbles;
    a copy with one new bubble added is still a copy."""
    return any(
        part == other
        or _similarity(part, other) >= _NEAR_COPY_SIMILARITY
        or _word_overlap(part, other) >= _SAME_WORDS_SIMILARITY
        for part in _parts(draft)
        for other in _parts(earlier)
    )


def _word_overlap(left: str, right: str) -> float:
    left_words, right_words = set(left.split()), set(right.split())
    return len(left_words & right_words) / len(left_words | right_words)


def _parts(text: str) -> list[str]:
    bubbles = text.split(REPLY_PART_SEPARATOR)
    parts = [text.replace(REPLY_PART_SEPARATOR, " "), *bubbles] if len(bubbles) > 1 else [text]
    normalized = (_normalize(part) for part in parts)
    return [part for part in normalized if len(part.split()) >= _MIN_WORDS_FOR_REPEAT_CHECK]


def _opening(text: str) -> str | None:
    """The lead-in before the first comma or stop, e.g. "that's awesome" or "long day at work"."""
    lead = re.split(r"[,.!?;:\u0964]", text.strip(), maxsplit=1)[0]
    words = _normalize(lead).split()
    if not 2 <= len(words) <= _OPENING_MAX_WORDS:
        return None
    return " ".join(words)


def _normalize(text: str) -> str:
    cleaned = text.casefold().replace("’", "'")
    cleaned = re.sub(r"[^\w\s']", " ", cleaned)
    return " ".join(cleaned.split())


def _similarity(left: str, right: str) -> float:
    """Jaccard overlap of word pairs; robust to small wording changes."""
    left_pairs, right_pairs = _pairs(left), _pairs(right)
    if not left_pairs or not right_pairs:
        return 0.0
    return len(left_pairs & right_pairs) / len(left_pairs | right_pairs)


def _pairs(text: str) -> set[tuple[str, str]]:
    words = text.split()
    return set(zip(words, words[1:], strict=False))


__all__ = [
    "STOCK_PHRASES",
    "question_rule_reason",
    "recent_assistant_replies",
    "rewrite_instruction",
    "stale_reply_reason",
    "trim_questions",
    "without_copied_replies",
]
