"""Defines the single public version and rollout configuration for the agent runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, cast

PipelineVersion = Literal["v1", "v2"]
RolloutMode = Literal["off", "shadow", "live"]

_PIPELINE_VERSIONS = {"v1", "v2"}
_ROLLOUT_MODES = {"off", "shadow", "live"}


@dataclass(frozen=True)
class AgentPipelineConfig:
    """Validated settings plus capabilities derived for runtime consumers."""

    version: PipelineVersion
    rollout: RolloutMode

    @property
    def structured_turn_output(self) -> bool:
        return self.version == "v2"

    @property
    def inline_data_points(self) -> bool:
        return self.version == "v2" and self.rollout != "live"

    @property
    def conversation_state_enabled(self) -> bool:
        return self.version == "v2" and self.rollout in {"shadow", "live"}

    @property
    def conversation_state_shadow(self) -> bool:
        # Live thread writes are intentionally not part of the current rollout.
        return self.conversation_state_enabled

    @property
    def background_memory_enabled(self) -> bool:
        return self.version == "v2" and self.rollout in {"shadow", "live"}

    @property
    def live_memory_writes(self) -> bool:
        return self.version == "v2" and self.rollout == "live"

    @property
    def legacy_rules(self) -> bool:
        return self.version == "v1"


def agent_pipeline_config() -> AgentPipelineConfig:
    """Read and validate the two public runtime settings without hidden overrides."""
    version = os.getenv("AGENT_PIPELINE_VERSION", "v2").strip().lower()
    rollout = os.getenv("AGENT_ROLLOUT", "shadow").strip().lower()
    if version not in _PIPELINE_VERSIONS:
        raise ValueError(
            f"Unknown AGENT_PIPELINE_VERSION '{version}'. Expected one of: v1, v2."
        )
    if rollout not in _ROLLOUT_MODES:
        raise ValueError(
            f"Unknown AGENT_ROLLOUT '{rollout}'. Expected one of: off, shadow, live."
        )
    return AgentPipelineConfig(
        version=cast(PipelineVersion, version),
        rollout=cast(RolloutMode, rollout),
    )


__all__ = ["AgentPipelineConfig", "PipelineVersion", "RolloutMode", "agent_pipeline_config"]
