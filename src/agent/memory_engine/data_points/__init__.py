"""Owns the canonical data-point model, normalization, taxonomy, and context ranking.

Extraction, feedback, retrieval, and projections may use this package, but callers
should import its public functions from here instead of depending on internal helpers.
"""

from .models import DataPoint
from .normalization import normalize_data_point
from .ranking import rank_data_points_for_context
from .taxonomy import canonical_fact_type, canonical_turn_data_point_type, snake_key

__all__ = [
    "DataPoint",
    "canonical_fact_type",
    "canonical_turn_data_point_type",
    "normalize_data_point",
    "rank_data_points_for_context",
    "snake_key",
]
