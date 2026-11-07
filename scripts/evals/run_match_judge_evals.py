#!/usr/bin/env python3
"""Run the match judge on pairs who are known friends and on random pairs, four ways, and report
which amount of evidence separates them best (design: docs/matching-design.md, section 8.5).

Runs against the database in .env (real cards are the point), read only: nothing is saved on the
users. Example:

  .venv/bin/python scripts/evals/run_match_judge_evals.py --known USER1:USER2 --users USER1,USER2,USER3,USER4 --random-pairs 4

Reasons quote what people said, so they are printed only with --show-reasons.
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
load_dotenv(PROJECT_ROOT / ".env")
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent.evals.matching.judge_eval import RUNS, evaluate, pick_pairs, report  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--known", action="append", default=[], metavar="A:B", help="A pair of user ids who are friends; repeat for more.")
    parser.add_argument("--users", default="", help="Comma-separated user ids random pairs are drawn from (the known users are added).")
    parser.add_argument("--pool", default=None, help="A match pool id: its members join --users.")
    parser.add_argument("--random-pairs", type=int, default=None, help="How many random pairs (default: twice the known pairs, at least 4).")
    parser.add_argument("--runs", default=",".join(RUNS), help=f"Which runs, comma-separated (default all: {', '.join(RUNS)}).")
    parser.add_argument("--model", default=None, help="Judge model id; default is MATCH_REASONS_MODEL or the request-check model.")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--show-reasons", action="store_true")
    parser.add_argument("--no-save", action="store_true")
    return parser


async def _run(args: argparse.Namespace) -> int:
    known = []
    for item in args.known:
        a, sep, b = item.partition(":")
        if not sep or not a or not b:
            print(f"--known needs A:B, got {item!r}", file=sys.stderr)
            return 2
        known.append((a.strip(), b.strip()))
    users = {u.strip() for u in args.users.split(",") if u.strip()} | {u for pair in known for u in pair}
    if args.pool:
        from storage import match_pool_members_of

        users |= {m["user_id"] for m in match_pool_members_of(args.pool)}
    if not known and len(users) < 2:
        print("Give at least one --known pair or two --users.", file=sys.stderr)
        return 2
    random_pairs = args.random_pairs if args.random_pairs is not None else max(4, 2 * len(known))
    pairs = pick_pairs(known, sorted(users), random_pairs=random_pairs, seed=args.seed)
    runs = tuple(r.strip() for r in args.runs.split(",") if r.strip() in RUNS)
    print(f"{len(known)} known pairs, {len(pairs) - len(known)} random pairs, runs: {', '.join(runs)}")
    verdicts, summaries = await evaluate(pairs, runs=runs, model=args.model)
    text = report(verdicts, summaries, show_reasons=args.show_reasons)
    print(text)
    if not args.no_save:
        folder = PROJECT_ROOT / "reports" / "evals" / datetime.now().strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "match-judge.md"
        path.write_text(f"# Match judge eval\n\nModel `{args.model or os.environ.get('MATCH_REASONS_MODEL') or 'default'}` · {datetime.now():%Y-%m-%d %H:%M}\n\n{text}\n", encoding="utf-8")
        print(f"saved {path.relative_to(PROJECT_ROOT)}")
    return 0


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
