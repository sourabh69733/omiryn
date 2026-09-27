#!/usr/bin/env python3
"""Evaluate background memory proposals against realistic conversation batches."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
EXPLICIT_DATABASE_URL = os.environ.get("DATABASE_URL")
load_dotenv(PROJECT_ROOT / ".env")
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Evaluation usage events must never pollute the application database by default.
os.environ["DATABASE_URL"] = EXPLICIT_DATABASE_URL or "sqlite:///./data/omiryn_memory_eval_test.db"
os.environ.setdefault("AUTH_REQUIRED", "false")

from agent.evals.shared.offline import keep_mock_runs_offline  # noqa: E402
from agent.evals.behavior.reporting.live import TerminalProgressReporter  # noqa: E402
from agent.evals.behavior.reporting.writer import (  # noqa: E402
    attach_run_metadata,
    save_evaluation_reports,
)
from agent.config import agent_pipeline_config  # noqa: E402
from agent.evals.memory import (  # noqa: E402
    ProviderMemoryEvidenceJudge,
    calibration_report_payload,
    get_memory_shadow_scenario,
    list_memory_shadow_scenarios,
    run_memory_judge_calibration,
    run_memory_shadow_scenario,
    scenario_result_payload as v2_scenario_result_payload,
)
from agent.evals.memory.calibration import MEMORY_JUDGE_CALIBRATION_CASES  # noqa: E402
from agent.evals.memory.v3 import (  # noqa: E402
    get_memory_v3_scenario,
    list_memory_v3_scenarios,
    run_memory_v3_scenario,
    scenario_result_payload as v3_scenario_result_payload,
)
from agent.evals.memory.v3.calibration import (  # noqa: E402
    MEMORY_V3_JUDGE_CALIBRATION_CASES,
)
from agent.providers.gateway.registry import (  # noqa: E402
    PROVIDER_NAMES,
    provider_model,
)
from storage import init_db, reset_db  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate background memory extraction without changing live memories."
    )
    parser.add_argument(
        "--provider",
        default=os.getenv("AGENT_PROVIDER", "deepinfra"),
        choices=PROVIDER_NAMES,
        help="Memory extraction provider.",
    )
    parser.add_argument("--model", default=None, help="Memory extraction model override.")
    parser.add_argument(
        "--judge-provider",
        default=None,
        choices=PROVIDER_NAMES,
        help="Optional independent evidence-judge provider.",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Optional evidence-judge model; uses --provider when judge provider is omitted.",
    )
    parser.add_argument(
        "--calibration-only",
        action="store_true",
        help="Calibrate the evidence judge without running memory extraction scenarios.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenario_ids",
        help="Scenario id. Repeat for multiple cases; omit to run the complete suite.",
    )
    parser.add_argument(
        "--scenario-tag",
        action="append",
        dest="scenario_tags",
        help="Run cases containing every supplied tag.",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List available scenarios without model calls.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(
            os.getenv(
                "MEMORY_BACKGROUND_TIMEOUT_SECONDS",
                os.getenv("MEMORY_BACKGROUND_V2_TIMEOUT_SECONDS", "120"),
            )
        ),
        help="Timeout for each model call.",
    )
    parser.add_argument("--reset", action="store_true", help="Reset the evaluation database.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/evals"),
        help="Report directory (default: reports/evals).",
    )
    parser.add_argument("--output", type=Path, help="Optional explicit JSON report path.")
    parser.add_argument("--no-save", action="store_true", help="Do not save report files.")
    parser.add_argument("--quiet", action="store_true", help="Hide live progress.")
    parser.add_argument("--json", action="store_true", help="Print full JSON results.")
    return parser


@dataclass(frozen=True)
class MemoryEvaluationContract:
    """Version-selected evaluator behavior without adding another public flag."""

    memory_version: int
    stage: str
    suite_label: str
    prompt_version: str
    get_scenario: Callable[[str], Any]
    list_scenarios: Callable[..., tuple[Any, ...]]
    run_scenario: Callable[..., Any]
    result_payload: Callable[..., dict[str, Any]]
    calibration_cases: tuple[Any, ...]


def _evaluation_contract() -> MemoryEvaluationContract:
    if agent_pipeline_config().memory_contract_version == 3:
        return MemoryEvaluationContract(
            memory_version=3,
            stage="memory_v3_eval",
            suite_label="Canonical V3 memory suite",
            prompt_version="memory-v3",
            get_scenario=get_memory_v3_scenario,
            list_scenarios=list_memory_v3_scenarios,
            run_scenario=run_memory_v3_scenario,
            result_payload=v3_scenario_result_payload,
            calibration_cases=MEMORY_V3_JUDGE_CALIBRATION_CASES,
        )
    return MemoryEvaluationContract(
        memory_version=2,
        stage="memory_shadow_eval",
        suite_label="Memory shadow suite",
        prompt_version="memory-v2",
        get_scenario=get_memory_shadow_scenario,
        list_scenarios=list_memory_shadow_scenarios,
        run_scenario=run_memory_shadow_scenario,
        result_payload=v2_scenario_result_payload,
        calibration_cases=MEMORY_JUDGE_CALIBRATION_CASES,
    )


def _selected_scenarios(
    args: argparse.Namespace,
    *,
    contract: MemoryEvaluationContract | None = None,
):
    selected_contract = contract or _evaluation_contract()
    if args.scenario_ids and args.scenario_tags:
        raise ValueError("Use --scenario or --scenario-tag, not both.")
    if args.scenario_ids:
        return tuple(selected_contract.get_scenario(item) for item in args.scenario_ids)
    return selected_contract.list_scenarios(tags=tuple(args.scenario_tags or ()))


async def _run(args: argparse.Namespace, reporter: TerminalProgressReporter) -> dict:
    if args.reset:
        reset_db()
    else:
        init_db()
    os.environ["AGENT_PROVIDER"] = args.provider
    contract = _evaluation_contract()
    scenarios = _selected_scenarios(args, contract=contract)
    if not scenarios:
        raise ValueError("No memory scenarios matched the selection.")
    semantic_judge = None
    calibration_payload = None
    if args.judge_provider or args.judge_model:
        semantic_judge = ProviderMemoryEvidenceJudge(
            provider=args.judge_provider or args.provider,
            model=args.judge_model,
            timeout_seconds=args.timeout_seconds,
            event_sink=reporter,
            memory_version=contract.memory_version,
        )
    if args.calibration_only and semantic_judge is None:
        raise ValueError("--calibration-only requires --judge-provider or --judge-model.")
    if semantic_judge is not None:
        calibration = await run_memory_judge_calibration(
            semantic_judge,
            cases=contract.calibration_cases,
            event_sink=reporter,
        )
        calibration_payload = calibration_report_payload(calibration)
        if args.calibration_only or not calibration.passed:
            return {
                "stage": "memory_judge_calibration",
                "passed": calibration.passed,
                "judges": [semantic_judge.judge_name],
                "judge_calibration": calibration_payload,
            }

    records = []
    for scenario in scenarios:
        result = await contract.run_scenario(
            scenario=scenario,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
            event_sink=reporter,
            semantic_judge=semantic_judge,
        )
        records.append(contract.result_payload(result, scenario=scenario))
    passed = sum(record["passed"] is True for record in records)
    structural_failures = sum(not record["observed"]["structurally_valid"] for record in records)
    judges = ["deterministic expected-versus-proposed memory behavior"]
    if semantic_judge is not None:
        judges.append(semantic_judge.judge_name)
    return {
        "stage": contract.stage,
        "passed": passed == len(records),
        "judges": judges,
        "judge_calibration": calibration_payload,
        "summary": {
            "total": len(records),
            "passed": passed,
            "failed": len(records) - passed,
            "structural_failures": structural_failures,
            "semantic_failures": sum(
                record["observed"].get("semantic_judgment") is not None
                and not record["observed"]["semantic_judgment"]["passed"]
                for record in records
            ),
            "semantic_judge_errors": sum(
                bool(record["observed"].get("semantic_judge_error")) for record in records
            ),
            "live_memory_writes": False,
        },
        "scenarios": records,
    }


def _output_dir(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def _print_scenarios(*, tags: tuple[str, ...]) -> None:
    contract = _evaluation_contract()
    scenarios = contract.list_scenarios(tags=tags)
    if not scenarios:
        print("No memory scenarios matched the selected tags.")
        return
    print(f"Available {contract.suite_label.lower()} scenarios:")
    for scenario in scenarios:
        expected = (
            ", ".join(
                f"{operation.operation}:"
                f"{getattr(operation, 'memory_kind', None) or getattr(operation, 'data_point_type', None) or 'existing'}"
                for operation in scenario.expected_operations
            )
            or "no change"
        )
        print(f"- {scenario.id} | expected={expected} | tags={','.join(scenario.tags)}")
        print(f"  {scenario.description}")


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    keep_mock_runs_offline(args.provider)
    if args.list_scenarios:
        _print_scenarios(tags=tuple(args.scenario_tags or ()))
        return 0
    if args.no_save and args.output:
        parser.error("--no-save cannot be combined with --output.")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive.")
    reporter = TerminalProgressReporter(enabled=not args.quiet)
    try:
        payload = asyncio.run(_run(args, reporter))
    except ValueError as error:
        parser.error(str(error))
    except Exception as error:
        payload = {
            "stage": "execution_error",
            "passed": False,
            "execution_error": f"{type(error).__name__}: {error}",
            "judges": [],
        }
    calibration_stage = payload.get("stage") == "memory_judge_calibration"
    contract = _evaluation_contract()
    metadata_provider = args.judge_provider or args.provider if calibration_stage else args.provider

    resolved_model = (
        args.judge_model or provider_model(metadata_provider) or "provider-default"
        if calibration_stage
        else args.model or provider_model(args.provider) or "provider-default"
    )
    attach_run_metadata(
        payload,
        stats=reporter.stats(),
        companion_provider=metadata_provider,
        companion_model=resolved_model,
        prompt_version=(
            f"memory-judge-v{contract.memory_version}"
            if calibration_stage
            else contract.prompt_version
        ),
        companion_agent_name=(
            "Memory evidence judge calibration"
            if calibration_stage
            else (
                "V3 background cognition"
                if contract.memory_version == 3
                else "Background memory extractor"
            )
        ),
    )
    if not args.no_save:
        paths = save_evaluation_reports(
            payload,
            output_dir=_output_dir(args.output_dir),
            explicit_json_path=args.output,
        )
        if not args.quiet:
            print(
                "\nReports saved:\n"
                f"  Easy report: {paths.markdown}\n"
                f"  Full data:   {paths.json}\n"
                f"  History:     {paths.history}",
                file=sys.stderr,
                flush=True,
            )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    elif payload["stage"] == "execution_error":
        print(f"Memory evaluation stopped: {payload['execution_error']}")
        return 1
    elif payload["stage"] == "memory_judge_calibration":
        calibration = payload["judge_calibration"]
        status = "PASS" if payload["passed"] else "FAIL"
        print(
            f"Memory judge calibration: {status}; "
            f"{calibration['completed_cases']}/{calibration['total_cases']} checked; "
            f"{calibration['judge_errors']} judge errors; "
            f"{calibration['issue_mismatches']} issue mismatches."
        )

    else:
        summary = payload["summary"]
        status = "PASS" if payload["passed"] else "FAIL"
        print(
            f"\n{contract.suite_label}: {status}; {summary['passed']}/{summary['total']} passed; "
            f"{summary['failed']} failed; {summary['structural_failures']} structural failures."
        )
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
