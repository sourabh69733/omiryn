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
