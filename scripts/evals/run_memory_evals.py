#!/usr/bin/env python3
"""Evaluate background memory proposals against realistic conversation batches."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
EXPLICIT_DATABASE_URL = os.environ.get("DATABASE_URL")
load_dotenv(PROJECT_ROOT / ".env")
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Evaluation usage events must never pollute the application database by default.
os.environ["DATABASE_URL"] = (
    EXPLICIT_DATABASE_URL or "sqlite:///./data/omiryn_memory_eval_test.db"
)
os.environ.setdefault("AUTH_REQUIRED", "false")

from agent.evals.behavior.reporting.live import TerminalProgressReporter  # noqa: E402
from agent.evals.behavior.reporting.writer import (  # noqa: E402
    attach_run_metadata,
    save_evaluation_reports,
)
from agent.evals.memory import (  # noqa: E402
    get_memory_shadow_scenario,
    list_memory_shadow_scenarios,
    run_memory_shadow_scenario,
    scenario_result_payload,
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
        default=float(os.getenv("MEMORY_BACKGROUND_V2_TIMEOUT_SECONDS", "120")),
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


def _selected_scenarios(args: argparse.Namespace):
    if args.scenario_ids and args.scenario_tags:
        raise ValueError("Use --scenario or --scenario-tag, not both.")
    if args.scenario_ids:
        return tuple(get_memory_shadow_scenario(item) for item in args.scenario_ids)
    return list_memory_shadow_scenarios(tags=tuple(args.scenario_tags or ()))


async def _run(args: argparse.Namespace, reporter: TerminalProgressReporter) -> dict:
    if args.reset:
        reset_db()
    else:
        init_db()
    os.environ["AGENT_PROVIDER"] = args.provider
    scenarios = _selected_scenarios(args)
    if not scenarios:
        raise ValueError("No memory scenarios matched the selection.")
    records = []
    for scenario in scenarios:
        result = await run_memory_shadow_scenario(
            scenario=scenario,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
            event_sink=reporter,
        )
        records.append(scenario_result_payload(result, scenario=scenario))
    passed = sum(record["passed"] is True for record in records)
    structural_failures = sum(
        not record["observed"]["structurally_valid"] for record in records
    )
    return {
        "stage": "memory_shadow_eval",
        "passed": passed == len(records),
        "judges": ["deterministic expected-versus-proposed memory behavior"],
        "summary": {
            "total": len(records),
            "passed": passed,
            "failed": len(records) - passed,
            "structural_failures": structural_failures,
            "live_memory_writes": False,
        },
        "scenarios": records,
    }


def _output_dir(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def _print_scenarios(*, tags: tuple[str, ...]) -> None:
    scenarios = list_memory_shadow_scenarios(tags=tags)
    if not scenarios:
        print("No memory scenarios matched the selected tags.")
        return
    print("Available memory shadow scenarios:")
    for scenario in scenarios:
        expected = ", ".join(
            f"{operation.operation}:{operation.data_point_type or 'existing'}"
            for operation in scenario.expected_operations
        ) or "no change"
        print(f"- {scenario.id} | expected={expected} | tags={','.join(scenario.tags)}")
        print(f"  {scenario.description}")


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
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
    resolved_model = args.model or provider_model(args.provider) or "provider-default"
    attach_run_metadata(
        payload,
        stats=reporter.stats(),
        companion_provider=args.provider,
        companion_model=resolved_model,
        prompt_version="memory-v2",
        companion_agent_name="Background memory extractor",
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
    else:
        summary = payload["summary"]
        status = "PASS" if payload["passed"] else "FAIL"
        print(
            f"\nMemory shadow suite: {status}; {summary['passed']}/{summary['total']} passed; "
            f"{summary['failed']} failed; {summary['structural_failures']} structural failures."
        )
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
