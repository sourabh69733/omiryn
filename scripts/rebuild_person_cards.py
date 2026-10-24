#!/usr/bin/env python3
"""Build the person card (facts about the other person, each with its real line) for uploads read
before cards existed, or rebuild them. One model call per 60 messages of each uploaded chat.

Dry run by default: lists the uploads. Pass --apply to build.

    PYTHONPATH=src python scripts/rebuild_person_cards.py --user <id> --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from agent.cognition.background.person_card import build_person_card  # noqa: E402
from agent.cognition.background.upload_read import upload_model  # noqa: E402
from agent.shared.timeline import user_zone  # noqa: E402
from storage import get_conversation, get_user_timezone, init_db  # noqa: E402
from storage.upload_digests import list_upload_digests, save_upload_digest  # noqa: E402


async def run(args: argparse.Namespace) -> int:
    init_db()
    zone = user_zone(get_user_timezone(args.user))
    for stored in list_upload_digests(args.user):
        partner = stored["partner_name"]
        messages = list((get_conversation(stored["conversation_id"], args.user) or {}).get("messages") or [])
        if not partner or not messages:
            continue
        if not args.apply:
            print(f"{partner}: {len(messages)} messages, would build a card")
            continue
        card = await build_person_card(messages, partner, zone, conversation_id=stored["conversation_id"], model=upload_model())
        save_upload_digest(stored["source_id"], args.user, stored["conversation_id"], partner, {**stored["digest"], "person_card": card})
        print(f"{partner}: {sum(len(facts) for facts in card.values())} facts in {', '.join(card) or 'no kinds'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", required=True, help="User id.")
    parser.add_argument("--apply", action="store_true", help="Build the cards.")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
