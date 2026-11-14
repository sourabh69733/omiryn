#!/usr/bin/env python3
"""Test the choosing match judge (judge v3, src/agent/matching/choose.py) on made-up people whose
right answer is planted: each has one friend, and one decoy who looks alike but would clash.

  # the judge alone, on notes written straight from the personas (no database needed)
  .venv/bin/python scripts/evals/run_match_choose_evals.py

  # the same with less known about each person
  .venv/bin/python scripts/evals/run_match_choose_evals.py --sample 6

  # people seeded through the real pipeline (scripts/evals/seed_match_personas.py)
  DATABASE_URL=sqlite:///./data/omiryn_match_eval.db .venv/bin/python scripts/evals/run_match_choose_evals.py \\
      --source db --people reports/evals/2026-11-10/match-personas.json

Costs model calls: about 20 per person at the default three rounds. Nothing is saved on any user.
The report goes to reports/evals/<date>/match-choose[-db].md.
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
load_dotenv(PROJECT_ROOT / ".env")
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent.evals.matching.choose_eval import (  # noqa: E402
    FIXTURE_DECOYS,
    FIXTURE_FRIENDS,
    TESTS,
    Round,
    build_cases,
    db_build,
    evaluate,
    fixture_build,
    fixture_people,
    report,
)
from agent.evals.matching.personas import MATCH_PERSONAS  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=("fixtures", "db"), default="fixtures")
    parser.add_argument("--people", default=None, help="With --source db: the match-personas.json a seeding run saved.")
    parser.add_argument("--tests", default=",".join(TESTS), help=f"Comma-separated (default all: {', '.join(TESTS)}).")
    parser.add_argument("--rounds", type=int, default=3, help="Times each ranking test runs, each with a new candidate order.")
    parser.add_argument("--sample", type=int, default=None, help="Fixtures only: keep this many notes per person, picked at random.")
    parser.add_argument("--model", default=None, help="Judge model id; default is MATCH_REASONS_MODEL or the request-check model.")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--no-confirm", action="store_true", help="Skip the second look at the first pick, to see the ranking alone.")
    parser.add_argument("--show-reasons", action="store_true")
    parser.add_argument("--no-save", action="store_true")
    return parser


async def _run(args: argparse.Namespace) -> int:
    tests = tuple(t.strip() for t in args.tests.split(",") if t.strip() in TESTS)
    if args.source == "fixtures":
        build = fixture_build(fixture_people(sample=args.sample, seed=args.seed))
        cases = build_cases(FIXTURE_FRIENDS, FIXTURE_DECOYS, seed=args.seed)
    else:
        if not args.people:
            print("--source db needs --people <match-personas.json>", file=sys.stderr)
            return 2
        seeded = {item["persona"]: item["user_id"] for item in json.loads(Path(args.people).read_text(encoding="utf-8"))["people"]}
        friends = {p.id: p.friend for p in MATCH_PERSONAS if p.id in seeded and p.friend in seeded}
        if len(friends) < 4:
            print(f"Only {len(friends)} seeded people have their friend seeded too; need at least 4.", file=sys.stderr)
            return 2
        # The decoys were never seeded, so the database source runs without them.
        build = db_build(seeded)
        cases = build_cases(friends, {}, seed=args.seed)

    def progress(result: Round) -> None:
        print(f"  {result.test:15} {result.person:8} -> {result.error or result.best or 'nobody'}", flush=True)

    print(f"{len(cases)} people, tests: {', '.join(tests)}, rounds: {args.rounds}, source: {args.source}")
    results = await evaluate(cases, build, tests=tests, rounds=args.rounds, model=args.model, seed=args.seed, confirm=not args.no_confirm, progress=progress)
    text = report(results, cases, show_reasons=args.show_reasons)
    print()
    print(text)
    if not args.no_save:
        folder = PROJECT_ROOT / "reports" / "evals" / datetime.now().strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        name = "match-choose" + ("-db" if args.source == "db" else "") + (f"-sample{args.sample}" if args.sample else "") + ("-no-confirm" if args.no_confirm else "") + ".md"
        model = args.model or os.environ.get("MATCH_REASONS_MODEL") or "default"
        (folder / name).write_text(f"# Choosing judge eval\n\nModel `{model}` · source {args.source} · {datetime.now():%Y-%m-%d %H:%M}\n\n{text}\n", encoding="utf-8")
        print(f"saved {(folder / name).relative_to(PROJECT_ROOT)}")
    return 0


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
