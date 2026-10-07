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
    for earlier in (_normalize(item) for item in earlier_replies):
        if text == earlier or _similarity(text, earlier) >= _NEAR_COPY_SIMILARITY:
            return f'it nearly repeats your earlier reply "{earlier[:80]}"'
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


def rewrite_instruction(draft: str, reason: str) -> str:
    """Appended to the system prompt for the single rewrite attempt."""
    return (
        "\n\nRewrite needed: your draft reply was "
        f'"{draft.strip()[:400]}". It needs a rewrite because {reason}. '
        "Write a different reply that responds specifically to the user's latest message, "
        "using what they actually said. Keep the same language, length and format rules."
    )


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
]
