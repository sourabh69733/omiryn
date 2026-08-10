"""Selects exactly one conversation data-point capture strategy.

The explicit DATA_POINT_CAPTURE_STRATEGY setting is preferred. Existing
AGENT_TURN_OUTPUT_VERSION and DATA_POINT_EXTRACTOR settings remain supported so old
deployments can roll back without allowing multiple strategies to run together.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

CaptureStrategy = Literal[
    "inline_llm",
    "background_llm",
    "hybrid_review",
    "legacy_rules",
    "disabled",
]

_STRATEGY_ALIASES: dict[str, CaptureStrategy] = {
    "inline": "inline_llm",
    "inline_llm": "inline_llm",
    "turn_output_v2": "inline_llm",
    "background": "background_llm",
    "background_llm": "background_llm",
    "llm": "background_llm",
    "hybrid": "hybrid_review",
    "hybrid_review": "hybrid_review",
    "legacy": "legacy_rules",
    "legacy_rules": "legacy_rules",
    "rules": "legacy_rules",
    "disabled": "disabled",
    "none": "disabled",
    "off": "disabled",
}


@dataclass(frozen=True)
class DataPointCapturePolicy:
    strategy: CaptureStrategy
    inline: bool = False
    immediate_rules: bool = False
    background_mode: Literal["llm", "hybrid"] | None = None


def data_point_capture_policy() -> DataPointCapturePolicy:
    explicit = os.getenv("DATA_POINT_CAPTURE_STRATEGY", "").strip().lower()
    if explicit:
        return _policy_for(_resolve_strategy(explicit))

    # Compatibility: V2 inline extraction wins over the old background/rule setting.
    # This prevents the historic behavior where both paths wrote the same message.
    turn_output_version = os.getenv("AGENT_TURN_OUTPUT_VERSION", "v2").strip().lower()
    if turn_output_version == "v2":
        return _policy_for("inline_llm")

    legacy_mode = os.getenv("DATA_POINT_EXTRACTOR", "hybrid").strip().lower()
    return _policy_for(_resolve_strategy(legacy_mode))


def _resolve_strategy(value: str) -> CaptureStrategy:
    strategy = _STRATEGY_ALIASES.get(value)
    if strategy is None:
        allowed = ", ".join(sorted(set(_STRATEGY_ALIASES.values())))
        raise ValueError(f"Unknown DATA_POINT_CAPTURE_STRATEGY '{value}'. Expected one of: {allowed}.")
    return strategy


def _policy_for(strategy: CaptureStrategy) -> DataPointCapturePolicy:
    if strategy == "inline_llm":
        return DataPointCapturePolicy(strategy=strategy, inline=True)
    if strategy == "legacy_rules":
        return DataPointCapturePolicy(strategy=strategy, immediate_rules=True)
    if strategy == "background_llm":
        return DataPointCapturePolicy(strategy=strategy, background_mode="llm")
    if strategy == "hybrid_review":
        return DataPointCapturePolicy(strategy=strategy, background_mode="hybrid")
    return DataPointCapturePolicy(strategy="disabled")
