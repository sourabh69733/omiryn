"""Defines provider exceptions exposed consistently to callers."""

from __future__ import annotations


class AgentProviderError(RuntimeError):
    pass


class AgentProviderTruncationError(AgentProviderError):
    """Raised when a provider stops because the configured output limit was reached."""
