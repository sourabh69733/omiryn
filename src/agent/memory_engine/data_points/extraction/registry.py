"""Derives exactly one data-point capture strategy from the agent pipeline config."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent.config import agent_pipeline_config

CaptureStrategy = Literal[
    "inline_llm",
    "background_llm",
    "hybrid_review",
    "legacy_rules",
    "disabled",
]

@dataclass(frozen=True)
class DataPointCapturePolicy:
    strategy: CaptureStrategy
    inline: bool = False
    immediate_rules: bool = False
    background_mode: Literal["llm", "hybrid"] | None = None


def data_point_capture_policy() -> DataPointCapturePolicy:
    config = agent_pipeline_config()
    if config.legacy_rules:
        return _policy_for("legacy_rules")
    if config.inline_data_points:
        return _policy_for("inline_llm")
    return _policy_for("disabled")


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
