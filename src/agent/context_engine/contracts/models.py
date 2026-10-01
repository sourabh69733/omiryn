"""Defines immutable contracts exchanged between context-engine stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


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
class ThreadReference:
    """Small private thread record used by foreground planning."""

    id: str
    title: str
    origin: str
    user_interest: str
    summary: str = ""
    next_angle: str | None = None
    cross_session: bool = False


@dataclass(frozen=True)
class ThreadGuidance:
    """Bounded active and relevant-open threads available to one turn."""

    active: ThreadReference | None = None
    relevant_open: tuple[ThreadReference, ...] = ()


@dataclass(frozen=True)
class AgentContext:
    user_profile: dict[str, Any] | None = None
    context_sources: list[dict[str, Any]] = field(default_factory=list)
    thread_guidance: ThreadGuidance = field(default_factory=ThreadGuidance)


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
    # Private V3.1 planning input. It is never a user-visible completion state.
    matching_discovery_allowed: bool = False
    matching_discovery_topics: tuple[str, ...] = ()
    thread_action: str = "none"
    thread_id: str | None = None
    thread_title: str | None = None
    thread_next_angle: str | None = None


@dataclass(frozen=True)
class MatchingDimensionProgress:
    id: str
    depth: str = "unknown"
    fact_count: int = 0
    evidence_count: int = 0
    confidence: float = 0.0


@dataclass(frozen=True)
class MatchingUnderstanding:
    level: str = "starting"
    breadth_percent: int = 0
    depth_percent: int = 0
    foundation_covered: int = 0
    foundation_total: int = 0
    dimensions: tuple[MatchingDimensionProgress, ...] = ()
    known_dimensions: tuple[str, ...] = ()
    unexplored_dimensions: tuple[str, ...] = ()
    can_deepen_dimensions: tuple[str, ...] = ()
    # (area id, line, "clear" | "mentioned") from the vibe card, and when the level was reached.
    area_lines: tuple[tuple[str, str, str], ...] = ()
    milestone_reached_at: datetime | None = None


@dataclass(frozen=True)
class ModelContextPackage:
    system_prompt: str
    context_sources: list[dict[str, Any]]
    user_profile: dict[str, Any] | None = None
    prompt_version: str | None = None
    prompt_version_name: str | None = None
    query_intent: ContextQueryIntent | None = None
    matching_understanding: MatchingUnderstanding | None = None
    thread_guidance: ThreadGuidance = field(default_factory=ThreadGuidance)
    snapshot: dict[str, Any] | None = None
    # Questions this reply may ask: 0 when the plan forbids one (cooldown, "no questions").
    question_limit: int = 1
