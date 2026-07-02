from __future__ import annotations

from typing import Any

MEMORY_STOP_WORDS = {
    "the",
    "and",
    "for",
    "you",
    "your",
    "about",
    "with",
    "from",
    "what",
    "that",
    "this",
    "tell",
    "me",
    "my",
    "can",
    "please",
    "hai",
    "tha",
    "thi",
    "kya",
    "kis",
    "kar",
    "karta",
    "karte",
    "raha",
    "rahe",
}


def normalized_memory_text(text: str) -> str:
    return " ".join(
        "".join(character.lower() if character.isalnum() else " " for character in text).split()
    )


def memory_terms(text: str) -> set[str]:
    normalized = normalized_memory_text(text)
    return {
        term
        for term in normalized.split()
        if len(term) >= 3 and term not in MEMORY_STOP_WORDS
    }


def source_identity(source: dict[str, Any]) -> str:
    metadata = source.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("original_source_id"):
        return str(metadata["original_source_id"])
    return str(source.get("id") or "")
