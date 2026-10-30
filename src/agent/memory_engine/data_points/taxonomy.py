"""Kept at its old import path. The fact-type taxonomy now live in `agent.shared.fact_taxonomy`: storage reads them from
there, so storage depends on nothing in the memory engine (the engine depends on storage)."""

from agent.shared.fact_taxonomy import (  # noqa: F401
    Any,
    PROFILE_FACT_CATEGORIES,
    annotations,
    canonical_fact_type,
    canonical_turn_data_point_type,
    re,
    snake_key,
)
