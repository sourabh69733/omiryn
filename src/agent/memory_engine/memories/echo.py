"""Keeps Omi from learning its own words as facts about the user.

The background model reads the user's lines next to Omi's. When Omi made something up ("Farheen
likes movies"), the model could save it as a memory citing the user's question. Code checks each new
memory: if most of its distinctive words come from Omi's lines in the batch and not from the user's
cited lines, it is an echo and is dropped. Plain paraphrase or translation is kept: those words are
not in Omi's lines either.

Some keys belong to one writer: "chat_partner.*" is written only by the upload reader, from the
uploaded chat itself.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from agent.memory_engine.processing.models import MemoryBatch

from .operations import MemoryAddProposal, MemoryAnalysisV3, MemorySupersedeProposal

UPLOAD_ONLY_KEY_PREFIXES = ("chat_partner.",)
# An echo: at least this many distinctive words only Omi said, and more than the user's.
ECHO_WORDS = 2
_WORD = re.compile(r"[\w']+")


def without_companion_echoes(analysis: MemoryAnalysisV3, batch: MemoryBatch) -> MemoryAnalysisV3:
    """The analysis without memories that repeat Omi's words or use an upload-only key."""
    by_index = {message.message_index: message for message in batch.messages}
    companion = _words(" ".join(message.content for message in batch.messages if message.role == "assistant"))
    kept, dropped = [], list(analysis.dropped)
    for operation in analysis.operations:
        memory = operation.replacement if isinstance(operation, MemorySupersedeProposal) else operation
        if isinstance(memory, MemoryAddProposal):
            if memory.key.startswith(UPLOAD_ONLY_KEY_PREFIXES):
                dropped.append(f"memory {memory.key}: only an upload writes this key")
                continue
            cited = " ".join(by_index[index].content for index in memory.evidence_message_indexes if index in by_index)
            if is_echo(f"{memory.statement or ''} {_value_text(memory.value)}", cited, companion):
                dropped.append(f"memory {memory.key}: repeats the companion's words, not the user's")
                continue
        kept.append(operation)
    if len(kept) == len(analysis.operations):
        return analysis
    return replace(analysis, operations=tuple(kept), dropped=tuple(dropped), decision="propose" if kept else "no_change")


def is_echo(memory_text: str, user_text: str, companion_words: set[str]) -> bool:
    words = _words(memory_text)
    users = _words(user_text)
    from_user = {word for word in words if _found(word, users)}
    only_companion = {word for word in words - from_user if _found(word, companion_words)}
    return len(only_companion) >= ECHO_WORDS and len(only_companion) > len(from_user)


def _found(word: str, words: set[str]) -> bool:
    """The word itself, or the same first 5 letters (movie/movies, discuss/discussing)."""
    return word in words or (len(word) >= 5 and any(len(other) >= 5 and other[:5] == word[:5] for other in words))


def _words(text: str) -> set[str]:
    # Distinctive words only: four letters or more ("the", "and", "with" match everything).
    return {word for word in _WORD.findall(text.casefold()) if len(word) >= 4 and not word.isdigit()}


def _value_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(str(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value or "")


__all__ = ["UPLOAD_ONLY_KEY_PREFIXES", "is_echo", "without_companion_echoes"]
