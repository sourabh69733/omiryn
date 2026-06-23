from __future__ import annotations

import hashlib
import math
import re
from typing import Any

LOCAL_TEXT_EMBEDDING_KIND = "local_hash_v1"
LOCAL_TEXT_EMBEDDING_DIMENSIONS = 128

DOMAIN_EXPANSIONS = {
    "baat": ("chat", "talk", "conversation", "message"),
    "baate": ("chat", "talk", "conversation", "messages", "topics"),
    "bol": ("talk", "tone", "style"),
    "bolta": ("talk", "tone", "style"),
    "call": ("phone", "voice"),
    "convo": ("chat", "conversation", "messages"),
    "message": ("chat", "text", "conversation"),
    "messages": ("chat", "texts", "conversation"),
    "meet": ("location", "place", "plan"),
    "msg": ("message", "chat", "text"),
    "place": ("location", "where", "kidhar", "wahi"),
    "rukna": ("wait", "location", "place"),
    "style": ("tone", "way", "talking"),
    "text": ("message", "chat"),
    "tone": ("style", "way", "talking"),
    "topic": ("conversation", "chat", "baat"),
    "topics": ("conversation", "chat", "baate"),
    "voice": ("call", "phone"),
    "wait": ("rukna", "location", "place"),
    "way": ("style", "tone"),
    "where": ("location", "place", "kidhar", "wahi"),
    "whatsapp": ("chat", "message", "conversation"),
}


def build_text_embedding(
    text: str,
    extra_terms: list[str] | set[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    tokens = _expanded_tokens(text, extra_terms)
    values = [0.0] * LOCAL_TEXT_EMBEDDING_DIMENSIONS
    for token in tokens:
        _add_feature(values, token, 1.0)
    for first, second in zip(tokens, tokens[1:]):
        _add_feature(values, f"{first}_{second}", 0.75)

    magnitude = math.sqrt(sum(value * value for value in values))
    if magnitude:
        values = [round(value / magnitude, 6) for value in values]

    return {
        "kind": LOCAL_TEXT_EMBEDDING_KIND,
        "dimensions": LOCAL_TEXT_EMBEDDING_DIMENSIONS,
        "values": values,
    }


def cosine_similarity(left: dict[str, Any] | None, right: dict[str, Any] | None) -> float:
    if not _is_compatible_embedding(left) or not _is_compatible_embedding(right):
        return 0.0
    left_values = left["values"]
    right_values = right["values"]
    return float(sum(float(a) * float(b) for a, b in zip(left_values, right_values)))


def _expanded_tokens(
    text: str,
    extra_terms: list[str] | set[str] | tuple[str, ...] | None,
) -> list[str]:
    tokens = _tokens(text)
    if extra_terms:
        tokens.extend(term for value in extra_terms for term in _tokens(str(value)))

    expanded = list(tokens)
    for token in tokens:
        expanded.extend(DOMAIN_EXPANSIONS.get(token, ()))
    return expanded


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[\w']+", text.lower(), flags=re.UNICODE)
        if len(token) >= 2
    ]


def _add_feature(values: list[float], feature: str, weight: float) -> None:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    raw = int.from_bytes(digest, "big")
    index = raw % LOCAL_TEXT_EMBEDDING_DIMENSIONS
    sign = 1.0 if (raw >> 7) & 1 else -1.0
    values[index] += sign * weight


def _is_compatible_embedding(value: dict[str, Any] | None) -> bool:
    return (
        isinstance(value, dict)
        and value.get("kind") == LOCAL_TEXT_EMBEDDING_KIND
        and value.get("dimensions") == LOCAL_TEXT_EMBEDDING_DIMENSIONS
        and isinstance(value.get("values"), list)
        and len(value["values"]) == LOCAL_TEXT_EMBEDDING_DIMENSIONS
    )
