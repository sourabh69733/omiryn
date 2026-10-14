#!/usr/bin/env python3
"""Run the topic-closure cases: once the user says a subject is over, does Omi let it go?

Real background model plus one real reply per closing case. Uses a separate SQLite test database.
No AI judge: results are checked in code. Prints a pass count per case and saves a Markdown report.
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
os.environ["DATABASE_URL"] = EXPLICIT_DATABASE_URL or "sqlite:///./data/omiryn_topic_closure_test.db"

from agent.evals.memory.closure import CLOSURE_CASES, run_closure_case, run_focus_marking_case  # noqa: E402
from storage import reset_db  # noqa: E402

_PROVIDER_TRIES = 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=2, help="Runs per case (default 2).")
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--no-reply", action="store_true", help="Skip the reply check (background only).")
    parser.add_argument("--no-save", action="store_true")
    return parser


async def _run(args: argparse.Namespace) -> int:
    os.environ.update({"AGENT_PIPELINE_VERSION": "v3", "AGENT_PROVIDER": "deepinfra", "MEMORY_EMBEDDING_MODEL": "off", "PROACTIVE_MESSAGING_ENABLED": "true"})
    background = os.environ.get("MEMORY_BACKGROUND_V2_MODEL") or "chat model"
    reply_model = os.environ.get("DEEPINFRA_MODEL") or "default"
    cases = [case for case in CLOSURE_CASES if not args.case_ids or case.id in args.case_ids]
    reset_db()
    lines = ["# Topic closure eval", "", f"Background `{background}` · reply `{reply_model}` · {args.runs} runs per case", ""]
    total = passed = 0
    for case in cases:
        results = []
        for _ in range(args.runs):
            for attempt in range(_PROVIDER_TRIES):
                result = await run_closure_case(case, check_reply=not args.no_reply)
                busy = any("429" in error or "Timeout" in error for error in result.errors)
                if not busy or attempt == _PROVIDER_TRIES - 1:
                    break
                await asyncio.sleep(5)
            results.append(result)
        wins = sum(result.passed for result in results)
        total += len(results)
        passed += wins
        print(f"{case.id}: {wins}/{len(results)} passed")
        lines += [f"## {case.id}: {wins}/{len(results)} passed", "", case.what, ""]
        for number, result in enumerate(results, 1):
            lines.append(f"- Run {number}: {'PASS' if result.passed else 'FAIL: ' + '; '.join(result.problems)}")
            lines.extend(f"  - memory {memory}" for memory in result.memories)
            lines.append(f"  - card: {result.card.replace(chr(10), ' | ')}")
            lines.append(f"  - left open: {result.left_open or '(nothing)'}")
            if result.greeting:
                lines.append(f"  - greeting: {result.greeting}")
            if result.reply:
                lines.append(f"  - reply: {result.reply}")
        lines.append("")
    if not args.case_ids or "focus_marked" in args.case_ids:
        marks = [await run_focus_marking_case() for _ in range(args.runs)]
        wins = sum(mark.passed for mark in marks)
        total += len(marks)
        passed += wins
        print(f"focus_marked: {wins}/{len(marks)} passed")
        lines += [f"## focus_marked: {wins}/{len(marks)} passed", "", "A new study topic is saved as a focus and kept out of the user card.", ""]
        for number, mark in enumerate(marks, 1):
            lines.append(f"- Run {number}: {'PASS' if mark.passed else 'FAIL'}")
            lines.extend(f"  - memory {memory}" for memory in mark.memories)
            lines.append(f"  - card: {mark.card.replace(chr(10), ' | ')}")
        lines.append("")
    summary = f"Total: {passed}/{total} passed"
    print(summary)
    lines.insert(3, summary)
    if not args.no_save:
        folder = PROJECT_ROOT / "reports" / "evals" / datetime.now().strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{datetime.now().strftime('%H%M%S')}__topic_closure.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Report: {path}")
    return 0 if passed == total else 1


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
