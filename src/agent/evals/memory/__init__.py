"""Evaluation contracts and runners for background memory extraction."""

from .calibration import (
    MEMORY_JUDGE_CALIBRATION_CASES,
    calibration_report_payload,
    run_memory_judge_calibration,
)
from .judge import ProviderMemoryEvidenceJudge
from .runner import MemoryScenarioResult, run_memory_shadow_scenario, scenario_result_payload
from .scenarios import (
    MEMORY_SHADOW_SCENARIOS,
    MemoryShadowScenario,
    get_memory_shadow_scenario,
    list_memory_shadow_scenarios,
)

__all__ = [
    "MEMORY_JUDGE_CALIBRATION_CASES",
    "MEMORY_SHADOW_SCENARIOS",
    "MemoryScenarioResult",
    "MemoryShadowScenario",
    "ProviderMemoryEvidenceJudge",
    "calibration_report_payload",
    "get_memory_shadow_scenario",
    "list_memory_shadow_scenarios",
    "run_memory_judge_calibration",
    "run_memory_shadow_scenario",
    "scenario_result_payload",
]
