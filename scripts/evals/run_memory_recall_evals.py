#!/usr/bin/env python3
"""Ask Omi questions about the user that need memories from other chats; score found and answered.

Uses a separate SQLite database, so synthetic users never enter the app database. No AI judge:
both checks are code. One reply call per case (plus embeddings).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
EXPLICIT_DATABASE_URL = os.environ.get("DATABASE_URL")
load_dotenv(PROJECT_ROOT / ".env")
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
os.environ["DATABASE_URL"] = EXPLICIT_DATABASE_URL or "sqlite:///./data/omiryn_memory_recall_test.db"

from agent.evals.memory.recall import (  # noqa: E402
    RECALL_CASES,
    recall_environment,
    recall_report,
    run_recall_case,
)
from storage import reset_db  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="deepinfra")
    parser.add_argument("--model", help="Reply model (default: the provider's configured model).")
    parser.add_argument("--prompt-version", help="Prompt version (default: the configured one).")
    parser.add_argument("--case", action="append", dest="case_ids", help="Run only this case.")
    parser.add_argument(
        "--no-noise", action="store_true", help="Seed only the memories a case needs (easy mode)."
    )
    parser.add_argument("--output-dir", type=Path, default=Path("reports/evals"))
    parser.add_argument("--no-save", action="store_true")
    return parser


async def _run(args: argparse.Namespace) -> int:
    cases = [case for case in RECALL_CASES if not args.case_ids or case.id in args.case_ids]
    if not cases:
        print(f"No such case. Available: {', '.join(case.id for case in RECALL_CASES)}")
        return 2
    os.environ.update(recall_environment(args.provider, args.prompt_version))
    prompt_version = os.environ.get("AGENT_BEHAVIOR_VERSION", "default")
    reset_db()
    results = []
    for case in cases:
        result = await run_recall_case(
            case, provider=args.provider, model=args.model, noise=not args.no_noise
        )
        mark = "PASS" if result.passed else "FAIL"
        print(f"{mark} {case.id}: found={result.found} answered={result.answered}")
        results.append(result)
    report = recall_report(
        results, model=args.model, prompt_version=prompt_version, noise=not args.no_noise
    )
    print()
    print(report)
    if not args.no_save:
        folder = args.output_dir if args.output_dir.is_absolute() else PROJECT_ROOT / args.output_dir
        folder = folder / datetime.now().strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        stem = folder / f"{datetime.now().strftime('%H%M%S')}__memory_recall"
        stem.with_suffix(".md").write_text(report, encoding="utf-8")
        stem.with_suffix(".json").write_text(
            json.dumps(
                [
                    {
                        "case": result.case.id,
                        "found": result.found,
                        "answered": result.answered,
                        "reply": result.reply,
                        "missing_memories": list(result.missing_memories),
                        "problems": list(result.problems),
                    }
                    for result in results
                ],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"Report: {stem.with_suffix('.md')}")
    return 0 if all(result.passed for result in results) else 1


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
