"""Defines the single public version and rollout configuration for the agent runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, cast

PipelineVersion = Literal["v1", "v2", "v3"]
RolloutMode = Literal["off", "shadow", "live"]

_PIPELINE_VERSIONS = {"v1", "v2", "v3"}
_ROLLOUT_MODES = {"off", "shadow", "live"}


@dataclass(frozen=True)
class AgentPipelineConfig:
    """Validated settings plus capabilities derived for runtime consumers."""

    version: PipelineVersion
    rollout: RolloutMode

    @property
    def foreground_reply_only(self) -> bool:
        return True

    @property
    def structured_turn_output(self) -> bool:
        """Deprecated compatibility signal; foreground output is always plain text."""
        return False

    @property
    def inline_data_points(self) -> bool:
        return False

    @property
    def conversation_state_enabled(self) -> bool:
        return self.version == "v3" or (
            self.version == "v2" and self.rollout in {"shadow", "live"}
        )

    @property
    def conversation_state_shadow(self) -> bool:
        return False

    @property
    def background_memory_enabled(self) -> bool:
        return self.version == "v3" or (
            self.version == "v2" and self.rollout in {"shadow", "live"}
        )

    @property
    def live_memory_writes(self) -> bool:
        return self.version == "v2" and self.rollout == "live"

    @property
    def live_v3_memory_writes(self) -> bool:
        return self.version == "v3"

    @property
    def live_thread_writes(self) -> bool:
        return self.version == "v3" or (
            self.version == "v2" and self.rollout == "live"
        )

    @property
    def memory_contract_version(self) -> int:
        return 3 if self.version == "v3" else 2

    @property
    def legacy_rules(self) -> bool:
        return self.version == "v1"


def agent_pipeline_config() -> AgentPipelineConfig:
    """Read and validate the two public runtime settings without hidden overrides."""
    # v3 is the only pipeline with the vibe card, user card, self-notes and session log.
    version = os.getenv("AGENT_PIPELINE_VERSION", "v3").strip().lower()
    # V3 is live by version alone. Rollout remains only for v1 and v2 compatibility.
    rollout = (
        "live"
        if version == "v3"
        else os.getenv("AGENT_ROLLOUT", "live").strip().lower()
    )
    if version not in _PIPELINE_VERSIONS:
        raise ValueError(
            f"Unknown AGENT_PIPELINE_VERSION '{version}'. Expected one of: v1, v2, v3."
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
