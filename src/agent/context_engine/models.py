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
    confidence: float = 0.0
    entities: tuple[str, ...] = ()
    is_low_information: bool = False


@dataclass(frozen=True)
class ContextBlock:
    id: str
    title: str
    content: str
    source: str
    priority: int = 10
    position: str = "middle"
    token_estimate: int = 0
    include_reason: str = ""
    skip_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TopicState:
    topic_id: str
    label: str
    bucket: str
    status: str
    depth: str = "shallow"
    last_seen_turns_ago: int | None = None
    repeat_count: int = 0
    user_interest: str = "unknown"


@dataclass(frozen=True)
class EmotionState:
    emotion: str = "neutral"
    intensity: str = "low"
    confidence: float = 0.0
    need: str = "normal_chat"
    strategy: str = "continue_naturally"
    response_mode: str = "normal_chat"
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConversationalStance:
    mode: str = "neutral"
    confidence: float = 0.0
    claim_type: str = "none"
    question_purpose: str = "none"
    constraints: tuple[str, ...] = ()
    feedback_kind: str | None = None
    reason: str = "No special stance needed."
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConversationPlan:
    current_move: str
    response_mode: str = "normal_chat"
    active_topic: str | None = None
    avoid_topics: tuple[str, ...] = ()
    suggested_topics: tuple[str, ...] = ()
    data_targets: tuple[str, ...] = ()
    tone_instruction: str = ""
    reason: str = ""
    stance: str = "neutral"
    stance_confidence: float = 0.0
    claim_type: str = "none"
    question_purpose: str = "optional"
    user_constraints: tuple[str, ...] = ()
    feedback_kind: str | None = None


@dataclass(frozen=True)
class ModelContextPackage:
    system_prompt: str
    context_sources: list[dict[str, Any]]
    user_profile: dict[str, Any] | None = None
    prompt_version: str | None = None
    prompt_version_name: str | None = None
    query_intent: ContextQueryIntent | None = None
    snapshot: dict[str, Any] | None = None
