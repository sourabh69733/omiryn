from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentContext:
    user_profile: dict[str, Any] | None = None
    context_sources: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ContextQueryIntent:
    labels: tuple[str, ...] = ()
    prefer_structured_whatsapp: bool = False


@dataclass(frozen=True)
class ModelContextPackage:
    system_prompt: str
    context_sources: list[dict[str, Any]]
    user_profile: dict[str, Any] | None = None
    prompt_version: str | None = None
    prompt_version_name: str | None = None
    query_intent: ContextQueryIntent | None = None
    snapshot: dict[str, Any] | None = None
