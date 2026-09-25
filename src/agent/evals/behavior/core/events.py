"""Defines progress events emitted by behavior evaluation workflows."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterator


@dataclass(frozen=True)
class EvalEvent:
    kind: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


EventSink = Callable[[EvalEvent], None]

# Names the conversation an event belongs to, so parallel samples stay readable in the log.
_sample_label: ContextVar[str | None] = ContextVar("eval_sample_label", default=None)


@contextmanager
def sample_label(label: str) -> Iterator[None]:
    token = _sample_label.set(label)
    try:
        yield
    finally:
        _sample_label.reset(token)


def emit_event(
    sink: EventSink | None,
    kind: str,
    summary: str,
    **data: Any,
) -> None:
    if sink is not None:
        label = _sample_label.get()
        if label is not None:
            data.setdefault("sample_label", label)
        sink(EvalEvent(kind=kind, message=summary, data=data))
