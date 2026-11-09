#!/usr/bin/env python3
"""Make up people for the match judge evaluation and let them chat with Omi for real.

Each persona from src/agent/evals/matching/personas.py is played by a model over several short
chats with the companion through the real runtime (one long sitting makes the persona model
repeat itself), background cognition writes their memories and vibe card after each chat,
embeddings are filled, the vibe card is backfilled if it is not yet ready, and their talk style
is counted. The result is a set of users whose cards were built the way real ones are,
in a database of their own, so the judge evaluation can run before any real pair exists:

  .venv/bin/python scripts/evals/seed_match_personas.py --sessions 4 --turns 8
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
from uuid import uuid4

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
    "your own day, plans, annoyances and opinions, and let what you care about come out over the chats "
    "rather than all at once. Never describe yourself in a list, and never repeat a line you already sent. "
    "Write like a person on a phone: one to three short lines a message. Keep going until the turns run out."
)
# A chat that fails in the persona model (a message too long, a bad reply) is tried again this often.
SESSION_ATTEMPTS = 3
# The persona model gets no memory between chats, so it is told what it already said.
TOLD_LIMIT_CHARS = 1500
# A persona model that sends the same line this many times has lost the thread; the chat ends there.
REPEAT_LIMIT = 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", default="", help="Comma-separated persona ids (default all).")
    parser.add_argument("--sessions", type=int, default=4, help="Chats per persona, each a new conversation.")
    parser.add_argument("--turns", type=int, default=8, help="User turns per chat.")
    parser.add_argument("--provider", default=os.getenv("AGENT_PROVIDER", "deepinfra"))
    parser.add_argument("--model", default=os.getenv("EVAL_MODEL") or "google/gemma-4-31B-it", help="Companion model.")
    parser.add_argument(
        "--user-model",
        default=os.getenv("REQUEST_CHECK_MODEL") or "Qwen/Qwen3-235B-A22B-Instruct-2507",
        help="Model that plays the persona; a small one repeats itself.",
    )
    parser.add_argument("--prompt", default=os.getenv("AGENT_BEHAVIOR_VERSION", "v4-3"), help="Companion prompt version.")
    parser.add_argument("--parallel", type=int, default=3, help="Personas chatting at the same time.")
    parser.add_argument(
        "--more",
        action="store_true",
        help="Give the people already in today's saved report --sessions more chats instead of making new users.",
    )
    parser.add_argument("--no-save", action="store_true")
    return parser


def _scenario(person: MatchPersona, turns: int, session: int, told: list[str]) -> SimulatedUserScenario:
    goal = GOAL
    if session:
        said = ""
        for line in reversed(told):
            if len(said) + len(line) > TOLD_LIMIT_CHARS:
                break
            said = f"- {line}\n{said}"
        goal += (
            f" This is your chat number {session + 1} with Omi, on a later day; Omi remembers your earlier chats. "
            "Bring something new from your life today (work, the weekend, family, a plan, an opinion, something from "
            f"your past), not the same topics or jokes as before. Things you already told it, which you must not repeat:\n{said}"
        )
    return SimulatedUserScenario(
        id=f"match-{person.id}",
        description=f"{person.name} gets to know Omi.",
        persona=person.persona,
        goal=goal,
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


def _repeating(turns) -> bool:
    lines = [t.user_message.strip().casefold() for t in turns]
    return bool(lines) and lines.count(lines[-1]) >= REPEAT_LIMIT


def _report_path() -> Path:
    return PROJECT_ROOT / "reports" / "evals" / datetime.now().strftime("%Y-%m-%d") / "match-personas.json"


def _existing_user(person: MatchPersona) -> str | None:
    """The user id today's report holds for this person, when there is one."""
    path = _report_path()
    if not path.exists():
        return None
    for row in json.loads(path.read_text()).get("people", []):
        if row.get("persona") == person.id and row.get("user_id"):
            return str(row["user_id"])
    return None


def _already_told(user_id: str) -> list[str]:
    return [
        str(m.get("content") or "")
        for conversation in list_conversations(user_id)
        for m in conversation["messages"]
        if m.get("role") == "user" and m.get("content")
    ]


async def _seed(person: MatchPersona, args: argparse.Namespace) -> dict:
    user_id = (_existing_user(person) if args.more else None) or f"ai-user-eval-match-{person.id}-{uuid4().hex[:8]}"
    save_user_profile(user_id, person.gender, "unknown", display_name=person.name, age=person.age, city="Pune")
    set_private_matching_consent(user_id, True)
    companion = RuntimeDriverConfig(provider=args.provider, model=args.model, prompt_version=args.prompt, agent_name="Omi")
    told: list[str] = _already_told(user_id) if args.more else []
    earlier_chats = len(list_conversations(user_id)) if args.more else 0
    turns_done = 0
    conversation_id = ""
    for session in range(earlier_chats, earlier_chats + args.sessions):
        print(f"[{person.id}] chat {session + 1} of {earlier_chats + args.sessions}, {args.turns} turns", flush=True)
        result = None
        for attempt in range(SESSION_ATTEMPTS):
            try:
                result = await run_simulated_conversation(
                    scenario=_scenario(person, args.turns, session, told),
                    simulated_user=ProviderSimulatedUser(provider=args.provider, model=args.user_model),
                    companion=companion,
                    user_id=user_id,
                )
                break
            except Exception as error:
                print(f"[{person.id}] chat {session + 1} attempt {attempt + 1} failed: {type(error).__name__}", flush=True)
        if result is None:
            continue
        kept = list(result.turns)
        if _repeating(kept):
            print(f"[{person.id}] chat {session + 1} looped after {len(kept)} turns", flush=True)
        told.extend(t.user_message for t in kept)
        turns_done += len(kept)
        conversation_id = result.conversation_id
        await _learn(user_id, conversation_id)
        while await refresh_user_memory_embeddings(user_id, conversation_id=conversation_id):
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
        "conversation_id": conversation_id,
        "turns": turns_done,
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
        out = _report_path()
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            # A rerun of some people (--only) replaces only their rows.
            earlier = json.loads(out.read_text())
            kept = [r for r in earlier.get("people", []) if r.get("persona") not in by_persona]
            payload["people"] = kept + rows
            ids = {r["persona"]: r.get("user_id") for r in payload["people"]}
            payload["known"] = [f"{ids[a]}:{ids[b]}" for a, b in KNOWN_FRIEND_PAIRS if ids.get(a) and ids.get(b)]
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"saved {out.relative_to(PROJECT_ROOT)}")
    return 0 if all(r.get("ready") for r in rows) else 1


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
