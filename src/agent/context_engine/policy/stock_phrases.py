"""Stock lines: replies that fit any message, found in real chats rather than guessed.

A hand-written seed covers the obvious ones. The rest are learned: short companion lines that
appear in many different conversations are, by definition, not about any one of them.
`scripts/find_stock_phrases.py` finds them and stores them in stock_phrases.json for review.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

LEARNED_PATH = Path(__file__).with_name("stock_phrases.json")
SEED_STOCK_PHRASES = (
    # Stock refusals: the reply is rewritten in the model's own words, never swapped for a template.
    "can't help with that",
    "cannot help with that",
    "can't assist with that",
    "cannot assist with that",
    "what's on your mind",
    "whats on your mind",
    "sometimes just relaxing is nice",
    # Praising "nothing" after a dry reply ("kuch nhi"), seen in real chats on several models.
    "kabhi kabhi 'kuch nahi'",
    "kabhi kabhi kuch nahi",
    "silent nights can be nice",
    "that sounds like fun",
    "that sounds amazing",
    "that sounds interesting",
    "i'm here for you",
    "im here for you",
    "how can i help you",
    "tell me more about it",
    "that's great to hear",
    "thats great to hear",
    "i'm glad to hear that",
)
# "haha", "ok sure": short acknowledgements are normal everywhere, not stock.
MIN_WORDS = 3
MAX_WORDS = 8
DEFAULT_MIN_CONVERSATIONS = 5


def normalize_line(text: str) -> str:
    cleaned = text.casefold().replace("’", "'")
    cleaned = re.sub(r"[^\w\s']", " ", cleaned)
    return " ".join(cleaned.split())


def learned_stock_phrases(path: Path = LEARNED_PATH) -> tuple[str, ...]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    return tuple(str(item) for item in data.get("phrases", []) if str(item).strip())


def find_stock_lines(
    conversations: Iterable[list[dict[str, Any]]],
    *,
    min_conversations: int = DEFAULT_MIN_CONVERSATIONS,
) -> list[tuple[str, int]]:
    """Short companion bubbles that recur across at least `min_conversations` chats, most first.

    The first message of a chat is skipped: it is the fixed opening greeting by design.
    """
    seen_in: dict[str, set[int]] = defaultdict(set)
    for number, messages in enumerate(conversations):
        for message in messages[1:]:
            if message.get("role") != "assistant":
                continue
            line = normalize_line(str(message.get("content") or ""))
            if MIN_WORDS <= len(line.split()) <= MAX_WORDS:
                seen_in[line].add(number)
    found = [(line, len(chats)) for line, chats in seen_in.items() if len(chats) >= min_conversations]
    return sorted(found, key=lambda item: (-item[1], item[0]))


def save_learned_phrases(phrases: Iterable[str], path: Path = LEARNED_PATH) -> list[str]:
    """Merge into the reviewable file; returns the full learned list."""
    merged = sorted(set(learned_stock_phrases(path)) | {normalize_line(p) for p in phrases if p.strip()})
    path.write_text(
        json.dumps(
            {
                "note": "Learned by scripts/find_stock_phrases.py: companion lines seen in many "
                "different chats. Remove a line here if it is fine to repeat.",
                "phrases": merged,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return merged


STOCK_PHRASES = SEED_STOCK_PHRASES + learned_stock_phrases()

__all__ = [
    "LEARNED_PATH",
    "SEED_STOCK_PHRASES",
    "STOCK_PHRASES",
    "find_stock_lines",
    "learned_stock_phrases",
    "normalize_line",
    "save_learned_phrases",
]
