#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./data/omiryn_behavior_eval.db")
os.environ.setdefault("AUTH_REQUIRED", "false")

from agent.evals.behavior.calibration import (  # noqa: E402
    calibration_report_payload,
    run_judge_calibration,
)
from agent.evals.behavior.consensus import ConservativeConsensusJudge  # noqa: E402
from agent.evals.behavior.judge import ProviderRubricJudge  # noqa: E402
from agent.evals.behavior.live_reporter import TerminalProgressReporter  # noqa: E402
from agent.evals.behavior.report_writer import (  # noqa: E402
    attach_run_metadata,
    save_evaluation_reports,
)
from agent.evals.behavior.runner import (  # noqa: E402
    BehaviorEvalConfig,
    report_payload,
    run_behavior_evals,
)
from agent.evals.behavior.runtime_driver import (  # noqa: E402
    RuntimeDriverConfig,
    RuntimeScenarioDriver,
)
from agent.evals.behavior.scenarios import COMPANION_BEHAVIOR_SCENARIOS  # noqa: E402
from agent.runtime.providers.registry import (  # noqa: E402
    EVAL_PROVIDER_NAMES,
    PROVIDER_NAMES,
    provider_model,
)
from storage import init_db, reset_db  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run end-to-end, multi-turn companion behavior evaluations."
    )
    parser.add_argument(
        "--provider",
        default=os.getenv("AGENT_PROVIDER", "deepinfra"),
        choices=PROVIDER_NAMES,
        help="Provider used by the companion under evaluation.",
    )
    parser.add_argument("--model", default=None, help="Optional companion model override.")
    parser.add_argument(
        "--agent-name",
        default=os.getenv("AGENT_NAME", "Mira"),
        help="Companion persona name shown in the conversation and report.",
    )
    parser.add_argument(
        "--prompt-version",
        default="v3",
        choices=("v1", "v2", "v3"),
        help="Prompt behavior version under evaluation.",
    )
    parser.add_argument(
        "--judge-provider",
        default=os.getenv("AGENT_EVAL_JUDGE_PROVIDER") or os.getenv("AGENT_PROVIDER", "deepinfra"),
        choices=EVAL_PROVIDER_NAMES,
        help="Independent semantic-rubric judge provider. Mock deliberately fails closed.",
    )
    parser.add_argument(
        "--judge-model",
        action="append",
        dest="judge_models",
        help=(
            "Judge model override. Repeat for conservative multi-model consensus. "
            "Release mode requires at least two distinct judge models."
        ),
    )
    parser.add_argument(
        "--judge-timeout-seconds",
        type=float,
        default=float(os.getenv("AGENT_EVAL_JUDGE_TIMEOUT_SECONDS", "120")),
        help="Timeout for each judge-provider attempt (default: 120 seconds).",
    )
    parser.add_argument(
        "--judge-max-attempts",
        type=int,
        default=int(os.getenv("AGENT_EVAL_JUDGE_MAX_ATTEMPTS", "3")),
        help="Maximum attempts for transient judge failures (default: 3).",
    )
    parser.add_argument(
        "--mode",
        choices=("release", "smoke"),
        default="release",
        help=(
            "Release enforces calibrated multi-model consensus and at least 3 samples; "
            "smoke permits a single judge and fewer samples for debugging."
        ),
    )
    parser.add_argument(
        "--calibration-only",
        action="store_true",
        help="Calibrate the semantic judge(s) without calling the companion under test.",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=None,
        help="Override samples per scenario. Release runs should use at least 3.",
    )
    parser.add_argument("--suite", default="companion_behavior_v1")
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenario_ids",
        help="Run only the named scenario. Repeat to select multiple scenarios.",
    )
    parser.add_argument("--persist", action="store_true", help="Persist results for admin review.")
    parser.add_argument("--reset", action="store_true", help="Reset the dedicated eval database.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/evals"),
        help="Directory for Markdown, JSON, and history reports (default: reports/evals).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional explicit JSON path; a matching Markdown report is also written.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not save Markdown or JSON report files.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Hide live progress; the final summary and reports are still produced.",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON instead of summary.")
    return parser


async def _run(args: argparse.Namespace, reporter: TerminalProgressReporter) -> dict:
    if args.reset:
        reset_db()
    else:
        init_db()
    driver = RuntimeScenarioDriver(
        RuntimeDriverConfig(
            provider=args.provider,
            model=args.model,
            prompt_version=args.prompt_version,
            agent_name=args.agent_name,
        ),
        event_sink=reporter,
    )
    judge, judge_names = _build_judge(args, reporter)
    _validate_run_mode(args, judge_names)
    calibration = await run_judge_calibration(judge, event_sink=reporter)
    calibration_payload = calibration_report_payload(calibration)
    if args.calibration_only or not calibration.passed:
        return {
            "stage": "judge_calibration",
            "passed": calibration.passed,
            "mode": args.mode,
            "judges": list(judge_names),
            "judge_runtime": _judge_runtime_payload(args),
            "judge_calibration": calibration_payload,
        }
    report = await run_behavior_evals(
        scenarios=_selected_scenarios(args.scenario_ids),
        driver=driver,
        judge=judge,
        config=BehaviorEvalConfig(
            suite_name=args.suite,
            provider=args.provider,
            model=args.model,
            prompt_version=args.prompt_version,
            samples_override=args.samples,
            persist=args.persist,
        ),
        event_sink=reporter,
    )
    payload = report_payload(report)
    payload["stage"] = "behavior_evaluation"
    payload["mode"] = args.mode
    payload["judges"] = list(judge_names)
    payload["judge_runtime"] = _judge_runtime_payload(args)
    payload["judge_calibration"] = calibration_payload
    return payload


def _build_judge(args: argparse.Namespace, reporter: TerminalProgressReporter):
    models = args.judge_models or [None]
    judges = tuple(
        (
            f"{args.judge_provider}:{model or 'provider-default'}",
            ProviderRubricJudge(
                provider=args.judge_provider,
                model=model,
                timeout_seconds=args.judge_timeout_seconds,
                max_attempts=args.judge_max_attempts,
                event_sink=reporter,
            ),
        )
        for model in models
    )
    names = tuple(name for name, _judge in judges)
    if len(judges) == 1:
        return judges[0][1], names
    return ConservativeConsensusJudge(judges), names


def _judge_runtime_payload(args: argparse.Namespace) -> dict:
    return {
        "timeout_seconds": args.judge_timeout_seconds,
        "max_attempts": args.judge_max_attempts,
    }


def _validate_run_mode(args: argparse.Namespace, judge_names: tuple[str, ...]) -> None:
    if args.mode != "release":
        return
    if len(judge_names) < 2:
        raise ValueError(
            "Release mode requires at least two --judge-model values. "
            "Use --mode smoke only for local debugging."
        )
    if args.samples is not None and args.samples < 3:
        raise ValueError("Release mode requires --samples 3 or greater.")


def _selected_scenarios(scenario_ids: list[str] | None):
    if not scenario_ids:
        return COMPANION_BEHAVIOR_SCENARIOS
    requested = set(scenario_ids)
    selected = tuple(
        scenario for scenario in COMPANION_BEHAVIOR_SCENARIOS if scenario.id in requested
    )
    unknown = sorted(requested - {scenario.id for scenario in selected})
    if unknown:
        available = ", ".join(scenario.id for scenario in COMPANION_BEHAVIOR_SCENARIOS)
        raise ValueError(f"Unknown behavior scenarios {unknown}. Available: {available}")
    return selected


def _companion_model_name(args: argparse.Namespace) -> str:
    return args.model or provider_model(args.provider) or "provider-default"


def _resolved_output_dir(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
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
            "mode": args.mode,
            "judges": [
                f"{args.judge_provider}:{model}"
                for model in (args.judge_models or ["provider-default"])
            ],
            "judge_runtime": _judge_runtime_payload(args),
            "judge_calibration": {
                "passed": False,
                "accuracy": 0.0,
                "false_accepts": 0,
                "false_rejects": 0,
                "judge_errors": 1,
                "completed_cases": 0,
                "total_cases": 0,
                "cases": [],
            },
            "execution_error": f"{type(error).__name__}: {error}",
        }
    attach_run_metadata(
        payload,
        stats=reporter.stats(),
        companion_provider=args.provider,
        companion_model=_companion_model_name(args),
        prompt_version=args.prompt_version,
        companion_agent_name=args.agent_name,
    )
    saved_paths = None
    if not args.no_save:
        saved_paths = save_evaluation_reports(
            payload,
            output_dir=_resolved_output_dir(args.output_dir),
            explicit_json_path=args.output,
        )
        if not args.quiet:
            print(
                "\nReports saved:\n"
                f"  Easy report: {saved_paths.markdown}\n"
                f"  Full data:   {saved_paths.json}\n"
                f"  History:     {saved_paths.history}",
                file=sys.stderr,
                flush=True,
            )
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.json:
        print(rendered)
    else:
        if payload["stage"] == "execution_error":
            print(f"Evaluation stopped: {payload['execution_error']}")
            return 1
        if payload["stage"] == "judge_calibration":
            calibration = payload["judge_calibration"]
            status = "PASS" if calibration["passed"] else "FAIL"
            print(
                f"{status} semantic judge calibration: accuracy={calibration['accuracy']:.2f} "
                f"false_accepts={calibration['false_accepts']} "
                f"false_rejects={calibration['false_rejects']} "
                f"judge_errors={calibration['judge_errors']} "
                f"cases={calibration['completed_cases']}/{calibration['total_cases']}"
            )
            for case in calibration["cases"]:
                if not case["passed"]:
                    print(
                        f"  {case['id']}: expected_pass={case['expected_pass']} "
                        f"observed_pass={case['observed_pass']}"
                    )
            return 0 if payload["passed"] else 1
        print(
            "Companion behavior evals: "
            f"{payload['scenario_passed']}/{payload['scenario_passed'] + payload['scenario_failed']} "
            "scenarios passed"
        )
        for scenario in payload["scenarios"]:
            status = "PASS" if scenario["passed"] else "FAIL"
            print(
                f"{status} {scenario['scenario_id']} "
                f"sample_pass_rate={scenario['sample_pass_rate']:.2f}"
            )
            for sample in scenario["samples"]:
                for grade in sample["grades"]:
                    for finding in grade["findings"]:
                        print(
                            f"  sample={sample['sample_index']} turn={grade['turn_index']} "
                            f"{finding['code']}: {finding['message']}"
                        )
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
