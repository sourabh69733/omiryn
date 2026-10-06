"""What background cognition was unsure about, for the companion to ask when it fits.

When new user messages leave it unclear whether an existing memory still holds, the model keeps
the memory and adds a question instead of guessing. A later batch with the user's answer applies
it to memories and resolves the question. Invalid items are dropped one by one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.memory_engine.processing.models import MemoryBatch
from agent.shared.utils import is_non_empty_string

OPEN_QUESTION_RESOLUTIONS = ("answered", "dropped")
MAX_OPEN_QUESTION_CHARS = 200
# One doubt per batch is plenty; more would turn the companion into an interviewer.
MAX_OPEN_QUESTION_ADDS = 1
MAX_OPEN_QUESTION_CHANGES = 4


@dataclass(frozen=True)
class OpenQuestionAdd:
    text: str
    message_index: int
    about_memory_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class OpenQuestionResolve:
    question_id: str
    status: str


@dataclass(frozen=True)
class OpenQuestionChanges:
    adds: tuple[OpenQuestionAdd, ...] = ()
    resolves: tuple[OpenQuestionResolve, ...] = ()
    dropped: tuple[str, ...] = field(default=())

    @property
    def empty(self) -> bool:
        return not self.adds and not self.resolves


def validate_open_questions(
    raw: Any,
    *,
    batch: MemoryBatch,
    open_question_ids: set[str],
    memory_ids: set[str],
) -> OpenQuestionChanges:
    """Keep adds raised by a new user message and resolves of questions that are still open."""
    if not isinstance(raw, list):
        return OpenQuestionChanges()
    user_indexes = {
        message.message_index for message in batch.new_messages if message.role == "user"
    }
    adds: list[OpenQuestionAdd] = []
    resolves: list[OpenQuestionResolve] = []
    dropped: list[str] = []
    resolved: set[str] = set()
    for item in raw[:MAX_OPEN_QUESTION_CHANGES]:
        operation = item.get("operation") if isinstance(item, dict) else None
        if operation == "add":
            if len(adds) >= MAX_OPEN_QUESTION_ADDS:
                dropped.append(f"at most {MAX_OPEN_QUESTION_ADDS} new question per batch")
                continue
            question, reason = _add(item, user_indexes, memory_ids)
            if question:
                adds.append(question)
            else:
                dropped.append(reason)
        elif operation == "resolve":
            question_id = str(item.get("target_question_id") or "")
            status = item.get("status")
            if question_id in open_question_ids and question_id not in resolved and status in OPEN_QUESTION_RESOLUTIONS:
                resolves.append(OpenQuestionResolve(question_id, status))
                resolved.add(question_id)
            else:
                dropped.append("resolve needs an open target_question_id and status answered or dropped")
        else:
            dropped.append("operation must be add or resolve")
    return OpenQuestionChanges(tuple(adds), tuple(resolves), tuple(dropped))


def _add(
    item: dict[str, Any], user_indexes: set[int], memory_ids: set[str]
) -> tuple[OpenQuestionAdd | None, str]:
    text = " ".join(str(item.get("text") or "").split()) if is_non_empty_string(item.get("text")) else ""
    if not text or len(text) > MAX_OPEN_QUESTION_CHARS:
        return None, f"text must be 1-{MAX_OPEN_QUESTION_CHARS} characters"
    index = item.get("message_index")
    if isinstance(index, bool) or index not in user_indexes:
        return None, "message_index must be the new user message that raised the doubt"
    about = item.get("about_memory_ids")
    about_ids = tuple(str(memory_id) for memory_id in about if str(memory_id) in memory_ids) if isinstance(about, list) else ()
    return OpenQuestionAdd(text=text, message_index=index, about_memory_ids=about_ids), ""


__all__ = [
    "OpenQuestionAdd",
    "OpenQuestionChanges",
    "OpenQuestionResolve",
    "validate_open_questions",
]
