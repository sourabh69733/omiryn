"""Feature configuration for inline companion-turn data-point extraction."""

from __future__ import annotations

from agent.memory_engine.data_points.extraction.registry import data_point_capture_policy


def turn_output_v2_enabled() -> bool:
    return data_point_capture_policy().inline
