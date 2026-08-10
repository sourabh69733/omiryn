"""Assembles, budgets, selects, and snapshots model-facing dynamic context."""

from .budget import budget_context_sources, truncate_for_context
from .matching import build_matching_understanding
from .snapshot import build_context_snapshot, build_context_snapshot_v2
from .sources import (
    AGENT_BEHAVIOR_RULES_SOURCE_TYPE,
    DATA_POINT_SOURCE_TYPE,
    STYLE_CONTEXT_SOURCE_TYPES,
    WHATSAPP_STRUCTURED_SOURCE_TYPE,
    build_profile_extraction_context_sources,
    build_reply_context,
    build_reply_context_sources,
    selected_style_source_exists,
)

__all__ = [
    "AGENT_BEHAVIOR_RULES_SOURCE_TYPE",
    "DATA_POINT_SOURCE_TYPE",
    "STYLE_CONTEXT_SOURCE_TYPES",
    "WHATSAPP_STRUCTURED_SOURCE_TYPE",
    "budget_context_sources",
    "build_context_snapshot",
    "build_context_snapshot_v2",
    "build_matching_understanding",
    "build_profile_extraction_context_sources",
    "build_reply_context",
    "build_reply_context_sources",
    "selected_style_source_exists",
    "truncate_for_context",
]
