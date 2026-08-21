"""Evaluation contracts and runners for background memory extraction."""

from .runner import MemoryScenarioResult, run_memory_shadow_scenario, scenario_result_payload
from .scenarios import (
    MEMORY_SHADOW_SCENARIOS,
    MemoryShadowScenario,
    get_memory_shadow_scenario,
    list_memory_shadow_scenarios,
)

__all__ = [
    "MEMORY_SHADOW_SCENARIOS",
    "MemoryScenarioResult",
    "MemoryShadowScenario",
    "get_memory_shadow_scenario",
    "list_memory_shadow_scenarios",
    "run_memory_shadow_scenario",
    "scenario_result_payload",
]
