#!/usr/bin/env python3
"""Let made-up people be the other side of a match, so you can test the flow as yourself.

Test tooling: the app never imports this, and it refuses production, real groups and real accounts.
It works on the database the local server uses (DATABASE_URL from .env, or from the shell).

  1. Make the people (once; this costs model calls, two people are enough to start):
       .venv/bin/python scripts/evals/seed_match_personas.py --dev-database --only aarav,kabir
  2. Put them in a test group and get its join code:
       .venv/bin/python scripts/evals/play_match_people.py setup
     Join that group yourself in the app (Matches, join with a code).
  3. Pair yourself with one of them and have Omi ask both (or do it from the admin app):
       .venv/bin/python scripts/evals/play_match_people.py pair --pool <pool id> --me <your user id> --with aarav
  4. Keep them alive while you test, with the server running:
       .venv/bin/python scripts/evals/play_match_people.py play --pool <pool id>
     They say yes to the ask and answer your messages. Other endings:
       --answer pass     they say no
       --answer none     they stay silent, so the ask lapses
       --open-first      they write first after the introduction
       --wait 20         seconds before they act, to see unread badges and typing gaps
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
load_dotenv(PROJECT_ROOT / ".env")
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent.evals.matching.player import ANSWER_MODES, TEST_POOL_PREFIX, NotATestSetup, pair_and_ask, persona_of, play_once, setup_test_pool  # noqa: E402
from agent.matching.readiness import match_readiness  # noqa: E402
from storage import init_db  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("setup", help="Create the test group and put every made-up person in it.")
    setup.add_argument("--name", default=TEST_POOL_PREFIX, help=f"Group name; must start with \"{TEST_POOL_PREFIX}\".")
    pair = commands.add_parser("pair", help="Pair yourself with one made-up person and have Omi ask both.")
    pair.add_argument("--pool", required=True)
    pair.add_argument("--me", required=True, help="Your user id (admin app, Users).")
    pair.add_argument("--with", dest="persona", required=True, help="Persona id, e.g. aarav.")
    play = commands.add_parser("play", help="Play the made-up people until stopped.")
    play.add_argument("--pool", required=True)
    play.add_argument("--answer", choices=ANSWER_MODES, default="accept")
    play.add_argument("--open-first", action="store_true")
    play.add_argument("--wait", type=float, default=0.0, help="Seconds a made-up person waits before acting.")
    play.add_argument("--every", type=float, default=4.0, help="Seconds between looks.")
    play.add_argument("--once", action="store_true", help="One look, then stop.")
    play.add_argument("--provider", default=os.getenv("AGENT_PROVIDER", "deepinfra"))
    play.add_argument("--model", default=os.getenv("REQUEST_CHECK_MODEL") or "Qwen/Qwen3-235B-A22B-Instruct-2507", help="Model that plays the people.")
    return parser


async def _play(args: argparse.Namespace) -> None:
    print(f"Playing the made-up people in pool {args.pool}. Ctrl+C stops.", flush=True)
    while True:
        if args.wait:
            await asyncio.sleep(args.wait)
        for action in await play_once(args.pool, answer=args.answer, open_first=args.open_first, provider=args.provider, model=args.model):
            print(action.line(), flush=True)
        if args.once:
            return
        await asyncio.sleep(args.every)


def main() -> int:
    args = _parser().parse_args()
    init_db()
    try:
        if args.command == "setup":
            result = setup_test_pool(args.name)
            pool = result["pool"]
            print(f"Test group \"{pool['name']}\": pool id {pool['id']}, join code {pool['join_code']}")
            if not result["people"]:
                print("No made-up people in this database yet. Run seed_match_personas.py --dev-database first.")
            for user_id in result["people"]:
                readiness = match_readiness(user_id)
                print(f"  {persona_of(user_id).id}: {user_id} ready={readiness.ready}")  # type: ignore[union-attr]
        elif args.command == "pair":
            pair = asyncio.run(pair_and_ask(args.pool, args.me, args.persona))
            print(f"Pair {pair['id']} is {pair['status']}. Omi asks both once the server's job worker runs.")
        else:
            asyncio.run(_play(args))
    except NotATestSetup as error:
        print(f"Refused: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
