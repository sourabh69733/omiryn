"""Contracts describing a selectable companion instruction version."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PromptBehaviorVersion:
    version_id: str
    name: str
    base_prompt: str
    context_usage_rules: str
    prompt_contract: str
    reply_style: dict[str, object] = field(default_factory=dict)
    conversation_flow: dict[str, object] = field(default_factory=dict)
    data_point_targets: tuple[str, ...] = ()
    # The goal block of the blocks prompt; empty uses V4's.
    reply_goal: str = ""
    # What the context engine does for this version. A new version made with replace() keeps them.
    blocks_prompt: bool = False
    listener_first: bool = False
    matching_understanding: bool = False
    plans_turn: bool = False
    # Gives Omi what it can do now and how chats are kept, and says when the person is new to it.
    introduces_itself: bool = False
    knows_itself: bool = False
    engine_version: str = "context_v2"
