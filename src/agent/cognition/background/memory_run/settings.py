"""Knobs for the memory run, from the environment: when it runs, which model, how long it may take."""

from __future__ import annotations

import os

from agent.config import agent_pipeline_config
from agent.memory_engine.processing.context import DEFAULT_CONTEXT_OVERLAP

# Content failures on one batch before it is skipped (provider outages never count).
MAX_BATCH_CONTENT_FAILURES = 3


def background_cognition_enabled() -> bool:
    return agent_pipeline_config().background_memory_enabled


def background_cognition_threshold() -> int:
    try:
        return max(1, int(os.getenv("MEMORY_BACKGROUND_V2_THRESHOLD", "7")))
    except ValueError:
        return 7


def background_model(model: str | None) -> str | None:
    return os.getenv("MEMORY_BACKGROUND_V2_MODEL", "").strip() or model


def context_overlap() -> int:
    try:
        return max(0, int(os.getenv("MEMORY_BACKGROUND_V2_CONTEXT_OVERLAP", "12")))
    except ValueError:
        return DEFAULT_CONTEXT_OVERLAP


def timeout_seconds() -> float:
    try:
        # Nobody waits on this call; the room covers a slow provider on a big batch.
        return max(1.0, float(os.getenv("MEMORY_BACKGROUND_V2_TIMEOUT_SECONDS", "180")))
    except ValueError:
        return 180.0


def lease_seconds() -> float:
    """Keep the claim beyond the bounded provider timeout without another flag."""
    return timeout_seconds() + 30.0


def user_lease_seconds() -> float:
    """A whole run: the main call, the vibe proof check, then embeddings."""
    return timeout_seconds() * 2 + 60.0


__all__ = [
    "MAX_BATCH_CONTENT_FAILURES",
    "background_cognition_enabled",
    "background_cognition_threshold",
    "background_model",
    "context_overlap",
    "lease_seconds",
    "timeout_seconds",
    "user_lease_seconds",
]
