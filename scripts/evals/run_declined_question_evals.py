#!/usr/bin/env python3
"""Replay the declined-question chat (progress 6c) against the real reply model.

Omi asked what the user was doing, the user answered around it and then said "do not ask stupid
questions" and "english?". Pass: no later reply asks that question again in any words, and the
replies after "english?" are in English. Checked in code, no AI judge. Uses its own SQLite database.
"""

from __future__ import annotations

import argparse
import asyncio
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
os.environ["DATABASE_URL"] = EXPLICIT_DATABASE_URL or "sqlite:///./data/omiryn_declined_question_test.db"

from agent.evals.memory.declined_questions import FOLLOW_UPS, run_declined_question_case  # noqa: E402
from storage import reset_db  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3, help="Runs (default 3).")
    parser.add_argument("--model", default=None, help="Reply model id; default is the server's reply model.")
    parser.add_argument("--provider", default=os.environ.get("AGENT_PROVIDER", "deepinfra"))
    parser.add_argument("--no-save", action="store_true")
    return parser


async def _run(args: argparse.Namespace) -> int:
    os.environ.update({"AGENT_PIPELINE_VERSION": "v3", "AGENT_PROVIDER": args.provider, "MEMORY_EMBEDDING_MODEL": "off"})
    reset_db()
    lines = ["# Declined question eval", "", f"Reply model `{args.model or os.environ.get('DEEPINFRA_MODEL') or 'default'}` · {args.runs} runs", ""]
    passed = 0
    for number in range(1, args.runs + 1):
        result = await run_declined_question_case(args.model)
        passed += result.passed
        print(f"run {number}: {'PASS' if result.passed else 'FAIL'}")
        lines.append(f"## Run {number}: {'PASS' if result.passed else 'FAIL'}")
        for text, reply in zip(FOLLOW_UPS, result.replies):
            lines.append(f"- user: {text}\n  - omi: {reply}")
        lines.extend(f"- problem: {problem}" for problem in result.problems)
        lines.extend(f"- error: {error}" for error in result.errors)
        lines.append("")
    summary = f"Total: {passed}/{args.runs} passed"
    print(summary)
    lines.insert(3, summary)
    if not args.no_save:
        folder = PROJECT_ROOT / "reports" / "evals" / datetime.now().strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{datetime.now().strftime('%H%M%S')}__declined_question.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Report: {path}")
    return 0 if passed == args.runs else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(_parser().parse_args())))
