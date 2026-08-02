#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
load_dotenv(PROJECT_ROOT / ".env")
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./data/omiryn_behavior_eval.db")
os.environ.setdefault("AUTH_REQUIRED", "false")

from agent.evals.behavior.live_reporter import TerminalProgressReporter  # noqa: E402
from agent.evals.behavior.report_writer import (  # noqa: E402
    attach_run_metadata,
    save_evaluation_reports,
)
from agent.evals.behavior.runtime_driver import RuntimeDriverConfig  # noqa: E402
from agent.evals.behavior.simulated_runner import (  # noqa: E402
    run_simulated_conversation,
    simulated_conversation_payload,
)
from agent.evals.behavior.simulated_scenarios import (  # noqa: E402
    SIMULATED_USER_SCENARIOS,
    get_simulated_user_scenario,
)
from agent.evals.behavior.simulated_judge import ProviderConversationJudge  # noqa: E402
from agent.evals.behavior.simulated_user import ProviderSimulatedUser  # noqa: E402
from agent.runtime.providers.registry import (  # noqa: E402
    EVAL_PROVIDER_NAMES,
    PROVIDER_NAMES,
    provider_model,
)
from storage import init_db, reset_db  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Let an AI model act as a user in a live conversation with the companion."
    )
    parser.add_argument(
        "--provider",
        default=os.getenv("AGENT_PROVIDER", "deepinfra"),
        choices=PROVIDER_NAMES,
        help="Companion provider.",
    )
    parser.add_argument("--model", default=None, help="Companion model override.")
    parser.add_argument(
        "--agent-name",
        default=os.getenv("AGENT_NAME", "Mira"),
        help="Companion persona name shown in the conversation and report.",
    )
    parser.add_argument(
        "--prompt-version",
        default="v3",
        choices=("v1", "v2", "v3"),
        help="Companion prompt version.",
    )
    parser.add_argument(
        "--user-provider",
        default=os.getenv("AGENT_EVAL_USER_PROVIDER", "deepinfra"),
        choices=EVAL_PROVIDER_NAMES,
        help="Provider for the AI model acting as the user.",
    )
    parser.add_argument(
        "--user-model",
        default=os.getenv("AGENT_EVAL_USER_MODEL"),
        help="Model acting as the human user.",
    )
    parser.add_argument(
        "--scenario",
        default=SIMULATED_USER_SCENARIOS[0].id,
        help="AI-user scenario id.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="Optional maximum conversation turns override.",
    )
    parser.add_argument(
        "--user-timeout-seconds",
        type=float,
        default=float(os.getenv("AGENT_EVAL_USER_TIMEOUT_SECONDS", "120")),
        help="Timeout for each AI-user model attempt (default: 120 seconds).",
    )
    parser.add_argument(
        "--user-max-attempts",
        type=int,
        default=int(os.getenv("AGENT_EVAL_USER_MAX_ATTEMPTS", "3")),
        help="Maximum AI-user attempts for transient failures (default: 3).",
    )
    parser.add_argument(
        "--judge-provider",
        default=os.getenv("AGENT_EVAL_JUDGE_PROVIDER"),
        choices=EVAL_PROVIDER_NAMES,
        help="Provider for independent transcript judge. Defaults to --user-provider.",
    )
    parser.add_argument(
        "--judge-model",
        action="append",
        dest="judge_models",
        default=None,
        help="Independent transcript judge model. Repeat to run multiple independent judges.",
    )
    parser.add_argument(
        "--judge-timeout-seconds",
        type=float,
        default=float(os.getenv("AGENT_EVAL_JUDGE_TIMEOUT_SECONDS", "120")),
        help="Timeout for each independent judge attempt (default: 120 seconds).",
    )
    parser.add_argument(
        "--judge-max-attempts",
        type=int,
        default=int(os.getenv("AGENT_EVAL_JUDGE_MAX_ATTEMPTS", "3")),
        help="Maximum independent judge attempts for transient failures (default: 3).",
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
    parser.add_argument("--quiet", action="store_true", help="Hide live conversation progress.")
    parser.add_argument("--json", action="store_true", help="Print full JSON output.")
    return parser


async def _run(args: argparse.Namespace, reporter: TerminalProgressReporter) -> dict:
    if args.reset:
        reset_db()
    else:
        init_db()
    scenario = get_simulated_user_scenario(args.scenario)
    if args.max_turns is not None:
        if args.max_turns < scenario.minimum_turns:
            raise ValueError(
                f"--max-turns must be at least {scenario.minimum_turns} for this scenario."
            )
        scenario = replace(scenario, maximum_turns=args.max_turns)
    simulated_user = ProviderSimulatedUser(
        provider=args.user_provider,
        model=args.user_model,
        timeout_seconds=args.user_timeout_seconds,
        max_attempts=args.user_max_attempts,
        event_sink=reporter,
    )
    judge_provider = args.judge_provider or args.user_provider
    independent_judges = tuple(
        ProviderConversationJudge(
            provider=judge_provider,
            model=model,
            timeout_seconds=args.judge_timeout_seconds,
            max_attempts=args.judge_max_attempts,
            event_sink=reporter,
        )
        for model in (args.judge_models or [None])
    )
    result = await run_simulated_conversation(
        scenario=scenario,
        simulated_user=simulated_user,
        companion=RuntimeDriverConfig(
            provider=args.provider,
            model=args.model,
            prompt_version=args.prompt_version,
            agent_name=args.agent_name,
        ),
        independent_judges=independent_judges,
        event_sink=reporter,
    )
    return simulated_conversation_payload(
        result,
        simulated_user_provider=args.user_provider,
        simulated_user_model=_resolved_model(args.user_provider, args.user_model),
    )


def _resolved_model(provider: str, model: str | None) -> str:
    return model or provider_model(provider) or "provider-default"


def _output_dir(path: Path) -> Path:
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
            "execution_error": f"{type(error).__name__}: {error}",
            "simulated_user": {
                "provider": args.user_provider,
                "model": _resolved_model(args.user_provider, args.user_model),
            },
            "independent_judges": [
                {
                    "provider": args.judge_provider or args.user_provider,
                    "model": _resolved_model(args.judge_provider or args.user_provider, model),
                }
                for model in (args.judge_models or [None])
            ],
        }
    attach_run_metadata(
        payload,
        stats=reporter.stats(),
        companion_provider=args.provider,
        companion_model=_resolved_model(args.provider, args.model),
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
        print(f"AI-user conversation stopped: {payload['execution_error']}")
        return 1
    else:
        turns = sum(len(item["turns"]) for item in payload["conversations"])
        judgment = payload["user_judgment"]
        user_status = "PASS" if judgment["passed"] else "FAIL"
        consensus = payload.get("consensus") or {}
        consensus_status = "PASS" if consensus.get("passed") else "FAIL"
        print(
            f"AI-user conversation: {turns} turns; user verdict {user_status} "
            f"({judgment['average_score']:.1f}/4); consensus {consensus_status} "
            f"({consensus.get('passing_voices', 0)}/{consensus.get('total_voices', 0)} voices)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
