#!/usr/bin/env python3
"""Run the AI honesty cases: does Omi claim things only a person could have done?

Real reply model, several runs per message; a separate model checks each reply for a claimed human
experience. Uses a separate SQLite test database. Prints the claim count and saves a Markdown report.
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
os.environ["DATABASE_URL"] = EXPLICIT_DATABASE_URL or "sqlite:///./data/omiryn_ai_honesty_test.db"

from agent.evals.behavior.ai_honesty import HONESTY_CASES, run_honesty_case  # noqa: E402
from storage import reset_db  # noqa: E402

_PROVIDER_TRIES = 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3, help="Runs per case (default 3).")
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--no-save", action="store_true")
    return parser


async def _run(args: argparse.Namespace) -> int:
    os.environ.update({"AGENT_PIPELINE_VERSION": "v3", "AGENT_PROVIDER": "deepinfra", "MEMORY_EMBEDDING_MODEL": "off"})
    reply_model = os.environ.get("DEEPINFRA_MODEL") or "default"
    cases = [case for case in HONESTY_CASES if not args.case_ids or case[0] in args.case_ids]
    reset_db()
    lines = ["# AI honesty eval", "", f"Reply `{reply_model}` · {args.runs} runs per message", ""]
    total = claims = 0
    for case_id, message in cases:
        results = []
        for _ in range(args.runs):
            for attempt in range(_PROVIDER_TRIES):
                try:
                    results.append(await run_honesty_case(case_id, message))
                    break
                except Exception as error:  # provider hiccup: retry, then report it
                    if attempt == _PROVIDER_TRIES - 1:
                        print(f"{case_id}: error {type(error).__name__}")
                    await asyncio.sleep(5)
        hits = sum(result.claims for result in results)
        total += len(results)
        claims += hits
        print(f"{case_id}: {hits}/{len(results)} claimed")
        lines += [f"## {case_id}: {hits}/{len(results)} claimed", "", f"Message: {message}", ""]
        for result in results:
            mark = f"CLAIM ({result.quote})" if result.claims else "ok"
            lines.append(f"- {mark}: {result.reply}")
        lines.append("")
    summary = f"Total: {claims}/{total} replies claimed a human experience"
    print(summary)
    lines.insert(3, summary)
    if not args.no_save:
        folder = PROJECT_ROOT / "reports" / "evals" / datetime.now().strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{datetime.now().strftime('%H%M%S')}__ai_honesty.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Report: {path}")
    return 0 if claims == 0 else 1


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
