"""Keeps eval runs against the mock companion fully offline."""

from __future__ import annotations

import os


def keep_mock_runs_offline(provider: str | None) -> None:
    """A mock companion must not call real APIs. The scripts load .env, whose embedding key would
    otherwise send memory embeddings to the network: slow, flaky, and billed."""
    if (provider or "").strip().lower() == "mock":
        os.environ["MEMORY_EMBEDDING_MODEL"] = "off"


__all__ = ["keep_mock_runs_offline"]
