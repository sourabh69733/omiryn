#!/usr/bin/env python3
"""Run companion thread-management scenarios against shadow state proposals."""

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

# Thread evals create synthetic fixture rows. Keep those out of the application
# database unless the caller deliberately supplies DATABASE_URL in the shell.
os.environ["DATABASE_URL"] = (
    EXPLICIT_DATABASE_URL or "sqlite:///./data/omiryn_thread_eval_test.db"
)
os.environ.setdefault("AUTH_REQUIRED", "false")

from agent.evals.shared.offline import keep_mock_runs_offline  # noqa: E402
from agent.evals.behavior.simulation.runtime import RuntimeDriverConfig  # noqa: E402
from agent.evals.behavior.reporting.live import TerminalProgressReporter  # noqa: E402
from agent.evals.behavior.reporting.writer import (  # noqa: E402
    attach_run_metadata,
    save_evaluation_reports,
)
from agent.evals.behavior.simulation.thread_runner import (  # noqa: E402
    run_background_thread_management_scenario,
    run_thread_management_scenario,
    thread_scenario_payload,
)
from agent.evals.behavior.simulation.thread_scenario import (  # noqa: E402
    get_thread_management_scenario,
    list_thread_management_scenarios,
)
from agent.providers.gateway.registry import PROVIDER_NAMES, provider_model  # noqa: E402
from storage import init_db, reset_db  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate companion thread-management proposals without persisting them."
    )
    parser.add_argument(
        "--lane",
        default="background",
        choices=("background", "foreground"),
        help="Evaluate the new background cognition lane or the legacy foreground proposal.",
    )
    parser.add_argument(
        "--provider",
        default=os.getenv("AGENT_PROVIDER", "deepinfra"),
        choices=PROVIDER_NAMES,
        help="Companion provider.",
    )
    parser.add_argument("--model", default=None, help="Companion model override.")
    parser.add_argument(
        "--prompt-version",
        default="v3-1",
        choices=("v1", "v2", "v3", "v3-1"),
        help="Companion prompt version.",
    )
    parser.add_argument(
        "--agent-name",
        default=os.getenv("AGENT_NAME", "Mira"),
        help="Companion persona name.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenario_ids",
        help="Scenario id. Repeat to run several. Runs the complete suite when omitted.",
    )
    parser.add_argument(
        "--scenario-tag",
        action="append",
        dest="scenario_tags",
        help="Require a scenario tag. Repeat to require several tags.",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List available cases without making model calls.",
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
    parser.add_argument("--quiet", action="store_true", help="Hide live evaluation progress.")
    parser.add_argument("--json", action="store_true", help="Print full JSON results.")
    return parser


def _selected_scenarios(args: argparse.Namespace):
    if args.scenario_ids and args.scenario_tags:
        raise ValueError("Use --scenario or --scenario-tag, not both.")
    if args.scenario_ids:
        return tuple(get_thread_management_scenario(item) for item in args.scenario_ids)
    return list_thread_management_scenarios(tags=tuple(args.scenario_tags or ()))


async def _run(args: argparse.Namespace, reporter: TerminalProgressReporter) -> dict:
    if args.reset:
        reset_db()
    else:
        init_db()
    scenarios = _selected_scenarios(args)
    if not scenarios:
        raise ValueError("No thread-management scenarios matched the selection.")
    companion = RuntimeDriverConfig(
        provider=args.provider,
        model=args.model,
        prompt_version=args.prompt_version,
        agent_name=args.agent_name,
    )
    records = []
    scenario_runner = (
        run_background_thread_management_scenario
        if args.lane == "background"
        else run_thread_management_scenario
    )
    for scenario in scenarios:
        result = await scenario_runner(
            scenario=scenario,
            companion=companion,
            event_sink=reporter,
        )
        record = thread_scenario_payload(result, scenario=scenario)
        records.append(record)
    passed_count = sum(record["passed"] is True for record in records)
    return {
        "stage": "thread_management_shadow_eval",
        "passed": passed_count == len(records),
        "judges": ["deterministic expected-versus-proposed thread action"],
        "lane": args.lane,
        "companion": {
            "provider": args.provider,
            "model": args.model or provider_model(args.provider) or "provider-default",
            "prompt_version": args.prompt_version,
            "agent_name": args.agent_name,
        },
        "summary": {
            "total": len(records),
            "passed": passed_count,
            "failed": len(records) - passed_count,
        },
        "scenarios": records,
    }


def _output_dir(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def _print_scenarios(*, tags: tuple[str, ...]) -> None:
    scenarios = list_thread_management_scenarios(tags=tags)
    if not scenarios:
        print("No thread-management scenarios matched the selected tags.")
        return
    print("Available thread-management scenarios:")
    for scenario in scenarios:
        expected = scenario.expected_action.operation if scenario.expected_action else "none"
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
    attach_run_metadata(
        payload,
        stats=reporter.stats(),
        companion_provider=args.provider,
        companion_model=args.model or provider_model(args.provider) or "provider-default",
        prompt_version=args.prompt_version,
        companion_agent_name=args.agent_name,
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
        print(f"Thread evaluation stopped: {payload['execution_error']}")
        return 1
    else:
        summary = payload["summary"]
        status = "PASS" if payload["passed"] else "FAIL"
        print(
            f"\nThread {args.lane} shadow suite: {status}; "
            f"{summary['passed']}/{summary['total']} passed; "
            f"{summary['failed']} failed."
        )
    
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
