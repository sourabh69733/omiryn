#!/usr/bin/env python3
"""Run deterministic stress evaluation of canonical reply-memory retrieval."""

from __future__ import annotations

import argparse
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

# Synthetic memories must never enter the application database by default.
os.environ["DATABASE_URL"] = (
    EXPLICIT_DATABASE_URL or "sqlite:///./data/omiryn_memory_retrieval_test.db"
)
os.environ.setdefault("AUTH_REQUIRED", "false")

from agent.evals.behavior.reporting.live import TerminalProgressReporter  # noqa: E402
from agent.evals.behavior.reporting.writer import (  # noqa: E402
    attach_run_metadata,
    save_evaluation_reports,
)
from agent.evals.memory.retrieval_cases import (  # noqa: E402
    run_retrieval_cases_evaluation,
)
from agent.evals.memory.retrieval_stress import (  # noqa: E402
    run_retrieval_stress_evaluation,
)
from storage import init_db, reset_db  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stress-test deterministic memory retrieval with 100 synthetic memories."
    )
    parser.add_argument(
        "--suite",
        choices=("stress", "cases"),
        default="stress",
        help="stress: 100-memory fixture (default); cases: follow-up, paraphrase, Hinglish cases.",
    )
    parser.add_argument(
        "--keyword-only",
        action="store_true",
        help="cases suite: skip embeddings (no API calls) to measure keyword retrieval alone.",
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
    parser.add_argument("--json", action="store_true", help="Print full JSON results.")
    return parser


def _output_dir(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if args.no_save and args.output:
        parser.error("--no-save cannot be combined with --output.")

    reporter = TerminalProgressReporter(enabled=False)
    try:
        reset_db() if args.reset else init_db()
        payload = (
            run_retrieval_cases_evaluation(semantic=not args.keyword_only)
            if args.suite == "cases"
            else run_retrieval_stress_evaluation()
        )
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
        companion_provider="local",
        companion_model="deterministic",
        prompt_version="not applicable",
        companion_agent_name="canonical memory retrieval",
    )

    if not args.no_save:
        paths = save_evaluation_reports(
            payload,
            output_dir=_output_dir(args.output_dir),
            explicit_json_path=args.output,
        )
        print(
            "Reports saved:\n"
            f"  Easy report: {paths.markdown}\n"
            f"  Full data:   {paths.json}\n"
            f"  History:     {paths.history}",
            file=sys.stderr,
            flush=True,
        )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    elif payload["stage"] == "execution_error":
        print(f"Memory retrieval evaluation stopped: {payload['execution_error']}")
        return 1
    elif payload["stage"] == "memory_retrieval_cases_eval":
        summary = payload["summary"]
        print(
            f"Memory retrieval cases ({payload['retrieval_mode']}): "
            f"{'PASS' if payload['passed'] else 'FAIL'}; "
            f"keyword {summary['keyword_passed']}/{summary['keyword_total']}; "
            f"semantic {summary['semantic_passed']}/{summary['semantic_total']}."
        )
    else:
        metrics = payload["scenario"]["metrics"]
        status = "PASS" if payload["passed"] else "FAIL"
        print(
            f"Memory retrieval stress: {status}; "
            f"recall={metrics['target_recall']:.0%}; "
            f"precision={metrics['precision_at_k']:.0%}; "
            f"policy violations={metrics['policy_violation_count']}; "
            f"selected={metrics['selected_count']}/{metrics['selection_limit']}."
        )
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
