#!/usr/bin/env python3
"""Write or refresh match notes (src/agent/matching/notes.py) for users, outside the daily job.

  .venv/bin/python scripts/build_match_notes.py --user USER_ID [--user USER_ID ...]
  DATABASE_URL=sqlite:///./data/omiryn_match_eval_v2.db .venv/bin/python scripts/build_match_notes.py \\
      --people reports/evals/2026-11-15/match-personas.json --show

One model call per 12,000 characters of new messages. Prints counts only; --show also prints the
notes, and only for made-up evaluation users (ids starting with "ai-user-eval-").
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
load_dotenv(PROJECT_ROOT / ".env")
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent.matching.notes import notes_readiness, rebuild_match_notes  # noqa: E402
from storage import get_match_notes, init_db  # noqa: E402

EVAL_PREFIX = "ai-user-eval-"


async def _run(args: argparse.Namespace) -> int:
    init_db()
    users = list(args.user)
    if args.people:
        users += [row["user_id"] for row in json.loads(Path(args.people).read_text(encoding="utf-8"))["people"] if row.get("user_id")]
    if not users:
        print("Give --user or --people.", file=sys.stderr)
        return 2
    for user_id in users:
        result = await rebuild_match_notes(user_id, force=args.force, model=args.model)
        notes = (get_match_notes(user_id) or {}).get("notes") or []
        ready = notes_readiness(notes)
        print(f"{user_id}: {result['status']}, {len(notes)} notes, kinds: {', '.join(ready['kinds']) or 'none'}, ready: {ready['ready']}", flush=True)
        if args.show and user_id.startswith(EVAL_PREFIX):
            for note in notes:
                print(f"   {note['kind']:13} {note['text']}  [{len(note['evidence'])} messages]")
        elif args.show:
            print("   (notes are printed only for made-up evaluation users)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", action="append", default=[], help="A user id; repeat for more.")
    parser.add_argument("--people", default=None, help="A match-personas.json from a seeding run.")
    parser.add_argument("--force", action="store_true", help="Build even with fewer than eight new messages.")
    parser.add_argument("--model", default=None, help="Model id; default is MATCH_NOTES_MODEL or the request-check model.")
    parser.add_argument("--show", action="store_true")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
