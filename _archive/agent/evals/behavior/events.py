from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass(frozen=True)
class EvalEvent:
    kind: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


EventSink = Callable[[EvalEvent], None]


def emit_event(
    sink: EventSink | None,
    kind: str,
    summary: str,
    **data: Any,
) -> None:
    if sink is not None:
        sink(EvalEvent(kind=kind, message=summary, data=data))
