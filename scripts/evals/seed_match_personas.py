#!/usr/bin/env python3
"""Make up people for the match judge evaluation and let them chat with Omi for real.

Each persona from src/agent/evals/matching/personas.py is played by a model over a conversation
with the companion through the real runtime, then background cognition writes their memories and
vibe card, embeddings are filled, the vibe card is backfilled if it is not yet ready, and their
talk style is counted. The result is a set of users whose cards were built the way real ones are,
in a database of their own, so the judge evaluation can run before any real pair exists:

  .venv/bin/python scripts/evals/seed_match_personas.py --turns 30
  DATABASE_URL=sqlite:///./data/omiryn_match_eval.db .venv/bin/python scripts/evals/run_match_judge_evals.py \\
      --known <a>:<b> ... --random-pairs 6

The seeded ids and the --known arguments are saved under reports/evals/<date>/match-personas.json.
The development database from .env is never used unless DATABASE_URL is set in the shell.
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

DEFAULT_DATABASE_URL = "sqlite:///./data/omiryn_match_eval.db"
os.environ["DATABASE_URL"] = EXPLICIT_DATABASE_URL or DEFAULT_DATABASE_URL
os.environ.setdefault("AUTH_REQUIRED", "false")

from agent.cognition.background.memory_run.service import (  # noqa: E402
    has_pending_background_cognition,
    run_background_cognition,
)
from agent.cognition.background.vibe.backfill import backfill_user_vibe  # noqa: E402
from agent.evals.behavior.simulation.runner import run_simulated_conversation  # noqa: E402
from agent.evals.behavior.simulation.runtime import RuntimeDriverConfig  # noqa: E402
from agent.evals.behavior.simulation.user import ProviderSimulatedUser, SimulatedUserScenario  # noqa: E402
from agent.evals.matching.personas import KNOWN_FRIEND_PAIRS, MATCH_PERSONAS, MatchPersona  # noqa: E402
from agent.matching.readiness import match_readiness  # noqa: E402
from agent.matching.style import rebuild_user_style  # noqa: E402
from agent.memory_engine.memories.embeddings import refresh_user_memory_embeddings  # noqa: E402
from storage import init_db, list_agent_memories, list_conversations, save_user_profile  # noqa: E402
from storage.memory_embeddings import list_agent_memory_embeddings  # noqa: E402
from storage.vibe_cards import set_private_matching_consent  # noqa: E402

# A long chat holds several background batches; each run handles one.
MAX_BACKGROUND_RUNS = 40

GOAL = (
    "Chat with Omi the way you would with a new companion app over your first days in the city: casually, "
    "in your own words and your own language mix. Answer what it asks honestly from who you are, bring up "
    "your own day, plans, annoyances and opinions, and let what you care about come out over the conversation "
    "rather than all at once. Never describe yourself in a list. Keep going until the turns run out."
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", default="", help="Comma-separated persona ids (default all).")
    parser.add_argument("--turns", type=int, default=30, help="User turns per persona.")
    parser.add_argument("--provider", default=os.getenv("AGENT_PROVIDER", "deepinfra"))
    parser.add_argument("--model", default=os.getenv("EVAL_MODEL") or "google/gemma-4-31B-it", help="Companion model.")
    parser.add_argument("--user-model", default=None, help="Model that plays the persona (default: the provider's).")
    parser.add_argument("--prompt", default=os.getenv("AGENT_BEHAVIOR_VERSION", "v4-3"), help="Companion prompt version.")
    parser.add_argument("--parallel", type=int, default=3, help="Personas chatting at the same time.")
    parser.add_argument("--no-save", action="store_true")
    return parser


def _scenario(person: MatchPersona, turns: int) -> SimulatedUserScenario:
    return SimulatedUserScenario(
        id=f"match-{person.id}",
        description=f"{person.name} gets to know Omi.",
        persona=person.persona,
        goal=GOAL,
        user_profile={
            "display_name": person.name,
            "gender": person.gender,
            "interested_in": "unknown",
            "location": "Pune, India",
        },
        tags=("match_personas",),
        minimum_turns=turns,
        maximum_turns=turns,
    )


async def _learn(user_id: str, conversation_id: str) -> None:
    """Run what the idle flush job would, until nothing is pending."""
    for _ in range(MAX_BACKGROUND_RUNS):
        conversation = next((c for c in list_conversations(user_id) if c["id"] == conversation_id), None)
        messages = list(conversation["messages"]) if conversation else []
        if not has_pending_background_cognition(conversation_id, user_id, messages):
            return
        result = await run_background_cognition(conversation_id, user_id, messages)
        if result.get("status") in {"live_invalid", "live_error", "already_processing"}:
            print(f"  background stopped: {result.get('status')}", flush=True)
            return


async def _seed(person: MatchPersona, args: argparse.Namespace) -> dict:
    print(f"[{person.id}] chatting, {args.turns} turns", flush=True)
    result = await run_simulated_conversation(
        scenario=_scenario(person, args.turns),
        simulated_user=ProviderSimulatedUser(provider=args.provider, model=args.user_model),
        companion=RuntimeDriverConfig(provider=args.provider, model=args.model, prompt_version=args.prompt, agent_name="Omi"),
    )
    user_id = result.turns[0].user_id
    save_user_profile(user_id, person.gender, "unknown", display_name=person.name, age=person.age, city="Pune")
    set_private_matching_consent(user_id, True)
    print(f"[{person.id}] {len(result.turns)} turns done, learning", flush=True)
    await _learn(user_id, result.conversation_id)
    while await refresh_user_memory_embeddings(user_id, conversation_id=result.conversation_id):
        pass
    readiness = match_readiness(user_id)
    backfilled = None
    if not readiness.ready:
        backfilled = (await backfill_user_vibe(user_id, apply=True, force=True)).get("status")
        readiness = match_readiness(user_id)
    style = rebuild_user_style(user_id)
    memories = [m for m in list_agent_memories(user_id) if m.get("status") == "active"]
    embedded = len(list_agent_memory_embeddings(user_id, [str(m["id"]) for m in memories]))
    row = {
        "persona": person.id,
        "user_id": user_id,
        "conversation_id": result.conversation_id,
        "turns": len(result.turns),
        "memories": len(memories),
        "embedded": embedded,
        "milestone": readiness.milestone,
        "ready": readiness.ready,
        "missing_areas": list(readiness.missing_areas),
        "facts_known": sorted(readiness.facts_known),
        "facts_missing": list(readiness.facts_missing),
        "style_messages": int(style.get("message_count") or 0),
        "vibe_backfill": backfilled,
    }
    print(
        f"[{person.id}] memories={row['memories']} embedded={embedded} card={readiness.milestone} "
        f"ready={readiness.ready} facts={row['facts_known']} missing={row['missing_areas']}",
        flush=True,
    )
    return row


async def _run(args: argparse.Namespace) -> int:
    init_db()
    wanted = {p.strip() for p in args.only.split(",") if p.strip()}
    people = [p for p in MATCH_PERSONAS if not wanted or p.id in wanted]
    limit = asyncio.Semaphore(max(1, args.parallel))

    async def one(person: MatchPersona) -> dict:
        async with limit:
            try:
                return await _seed(person, args)
            except Exception as error:  # one failed persona must not lose the others
                print(f"[{person.id}] failed: {type(error).__name__}: {error}", flush=True)
                return {"persona": person.id, "error": f"{type(error).__name__}: {error}"}

    rows = await asyncio.gather(*(one(p) for p in people))
    by_persona = {row["persona"]: row.get("user_id") for row in rows}
    known = [
        f"{by_persona[a]}:{by_persona[b]}" for a, b in KNOWN_FRIEND_PAIRS if by_persona.get(a) and by_persona.get(b)
    ]
    payload = {
        "database_url": os.environ["DATABASE_URL"],
        "companion_model": args.model,
        "prompt_version": args.prompt,
        "people": rows,
        "known": known,
    }
    print(json.dumps({"known": known, "ready": [r["persona"] for r in rows if r.get("ready")]}, indent=2))
    if not args.no_save:
        out = PROJECT_ROOT / "reports" / "evals" / datetime.now().strftime("%Y-%m-%d") / "match-personas.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"saved {out.relative_to(PROJECT_ROOT)}")
    return 0 if all(r.get("ready") for r in rows) else 1


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
