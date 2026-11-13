"""Plays the made-up people as the other side of a match, so one real person can test the flow.

Test tooling only: nothing in the app imports this. A made-up person (an id the persona seeding
gave, `ai-user-eval-match-<persona>-...`) sits in a test group with the tester. This module does
what that person would do in the app: answer Omi's "want me to introduce you?" and write in the
chat with the tester, in the persona's voice, through the same functions the app's endpoints call.
It never plays a real account, never acts outside a test group and never runs in production.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.evals.behavior.simulation.user import ProviderSimulatedUser, SimulatedUserScenario

from .personas import MATCH_PERSONAS, MatchPersona

TEST_USER_PREFIX = "ai-user-eval-match-"
TEST_POOL_PREFIX = "Test people"
ANSWER_MODES = ("accept", "pass", "none")
# How much of the chat the persona model sees.
TRANSCRIPT_MESSAGES = 30
_NO_FINISH = 1_000_000

_GOAL = (
    "Omi, the companion app you use, introduced you to {name}, a real person from your group, because it thought "
    "you two would get along. You are now writing to {name} directly in the app, not to Omi. In the transcript, "
    "\"assistant\" lines are {name}'s messages and \"user\" lines are yours. Write your next message to {name} the "
    "way you would text someone you were just introduced to: your own voice and language mix, one to three short "
    "lines, reacting to what they actually said. Never repeat a line you already sent.{start}"
)
_FIRST = " Nobody has written yet, so you write first."
_STARTER = " Omi suggested an easy start: {icebreaker}"


class NotATestSetup(RuntimeError):
    """The player was pointed at production, a real group, or a real account."""


@dataclass(frozen=True)
class Action:
    user_id: str
    pair_id: str
    kind: str  # answered | replied
    detail: str

    def line(self) -> str:
        return f"{persona_of(self.user_id).name if persona_of(self.user_id) else self.user_id}: {self.kind} ({self.detail}) pair {self.pair_id}"


def persona_of(user_id: str) -> MatchPersona | None:
    """The made-up person behind a seeded id; None for every real account."""
    if not user_id.startswith(TEST_USER_PREFIX):
        return None
    persona_id = user_id[len(TEST_USER_PREFIX) :].rsplit("-", 1)[0]
    return next((person for person in MATCH_PERSONAS if person.id == persona_id), None)


def is_test_pool(pool: dict[str, Any] | None) -> bool:
    return bool(pool) and str(pool.get("name") or "").startswith(TEST_POOL_PREFIX)


def seeded_people() -> list[str]:
    """Every made-up person in this database."""
    from sqlalchemy import select

    from storage.database import ENGINE
    from storage.schema import user_profiles

    with ENGINE.begin() as connection:
        rows = connection.execute(select(user_profiles.c.user_id).where(user_profiles.c.user_id.like(f"{TEST_USER_PREFIX}%"))).all()
    return sorted(row[0] for row in rows if persona_of(row[0]))


def _guard(pool_id: str) -> list[str]:
    """The made-up members of a test group; refuses anything else."""
    from security.auth import production_runtime_enabled
    from storage import get_match_pool, match_pool_members_of

    if production_runtime_enabled():
        raise NotATestSetup("the player does not run in production")
    pool = get_match_pool(pool_id)
    if not is_test_pool(pool):
        raise NotATestSetup(f"pool {pool_id} is not a test group (its name must start with \"{TEST_POOL_PREFIX}\")")
    return [m["user_id"] for m in match_pool_members_of(pool_id) if persona_of(m["user_id"])]


def setup_test_pool(name: str = TEST_POOL_PREFIX) -> dict[str, Any]:
    """Create the test group (or reuse the one with this name) and put every made-up person in it."""
    from security.auth import production_runtime_enabled
    from storage import create_match_pool, join_match_pool, list_match_pools

    if production_runtime_enabled():
        raise NotATestSetup("the player does not run in production")
    if not name.startswith(TEST_POOL_PREFIX):
        raise NotATestSetup(f"a test group's name must start with \"{TEST_POOL_PREFIX}\"")
    pool = next((p for p in list_match_pools() if p["name"] == name), None) or create_match_pool(name, created_by="match-player")
    people = seeded_people()
    for user_id in people:
        join_match_pool(user_id, pool["join_code"])
    return {"pool": pool, "people": people}


async def pair_and_ask(pool_id: str, tester_id: str, persona_id: str) -> dict[str, Any]:
    """Pair the tester with one made-up person and have Omi ask both, as the operator would."""
    from agent.matching.asking import ask_pair
    from agent.matching.pool import propose_pair
    from storage import set_match_pair_status

    people = _guard(pool_id)
    other = next((user_id for user_id in people if persona_of(user_id).id == persona_id), None)  # type: ignore[union-attr]
    if other is None:
        raise NotATestSetup(f"no made-up person \"{persona_id}\" in this test group")
    pair = await propose_pair(pool_id, tester_id, other, created_by="match-player")
    check = pair.get("check") or {}
    if not check.get("reasons"):
        # Not asked: a candidate does not hold either person back from another pair.
        set_match_pair_status(pair["id"], "candidate")
        raise NotATestSetup(
            f"nothing to tell them yet: {check.get('why_not') or 'the judge found no reasons'}. "
            "Give the made-up person more chats (seed_match_personas.py --dev-database --more) or fill in your own vibe."
        )
    return await ask_pair(pair["id"], created_by="match-player")


async def play_once(
    pool_id: str, *, answer: str = "accept", open_first: bool = False, provider: str = "mock", model: str | None = None
) -> list[Action]:
    """One pass over the test group: each made-up person answers an open ask and replies where it is their turn."""
    from agent.matching.asking import record_answer
    from agent.matching.hosting import pair_facts
    from agent.matching.pair_chat import chat_state
    from realtime import realtime_hub
    from realtime.contracts import user_event
    from storage import add_match_message, list_match_messages, mark_match_chat_read, match_pairs_for_user

    if answer not in ANSWER_MODES:
        raise ValueError(f"answer must be one of {', '.join(ANSWER_MODES)}")
    actions: list[Action] = []
    for user_id in _guard(pool_id):
        person = persona_of(user_id)
        assert person is not None
        for pair in match_pairs_for_user(user_id):
            if pair["pool_id"] != pool_id:
                continue
            plan = pair.get("plan") or {}
            heard = user_id in (plan.get("told") or {})
            if pair["status"] == "asked" and heard and user_id not in (plan.get("answers") or {}) and answer != "none":
                result = record_answer(pair["id"], user_id, answer)
                actions.append(Action(user_id, pair["id"], "answered", f"{answer}, pair now {result.get('status')}"))
                continue
            if not chat_state(pair, user_id)["open"]:
                continue
            messages = list_match_messages(pair["id"], limit=TRANSCRIPT_MESSAGES)
            their_turn = bool(messages) and messages[-1]["sender_id"] != user_id
            if not their_turn and not (open_first and not messages):
                continue
            name = pair_facts(pair, user_id)["name"]
            icebreaker = (pair.get("check") or {}).get("icebreaker")
            start = (_FIRST + (_STARTER.format(icebreaker=icebreaker) if icebreaker else "")) if not messages else ""
            scenario = SimulatedUserScenario(
                id=f"match-chat-{person.id}",
                description=f"{person.name} writes to {name}, someone Omi introduced.",
                persona=person.persona,
                goal=_GOAL.format(name=name, start=start),
                user_profile={"display_name": person.name},
                minimum_turns=_NO_FINISH,
                maximum_turns=_NO_FINISH,
            )
            transcript = tuple({"role": "user" if m["sender_id"] == user_id else "assistant", "content": m["text"]} for m in messages)
            mine = sum(1 for m in messages if m["sender_id"] == user_id)
            # Their screen shows the dots while the model writes, as a person's would.
            await realtime_hub.publish(user_event("match.typing", pair_facts(pair, user_id)["other_id"], payload={"pair_id": pair["id"], "active": True}))
            decision = await ProviderSimulatedUser(provider=provider, model=model).next_turn(
                scenario=scenario, transcript=transcript, turn_index=mine, conversation_id=f"match-chat:{pair['id']}"
            )
            text = (decision.message or "").strip()
            if not text:
                continue
            sent = add_match_message(pair["id"], user_id, text)
            if sent is None:
                continue
            mark_match_chat_read(pair["id"], user_id, sent["id"])
            # The running server picks these up from the shared event log and pushes them to the tester's screen.
            for target in (pair["user_a"], pair["user_b"]):
                await realtime_hub.publish(user_event("match.message", target, payload={"pair_id": pair["id"], "message_id": sent["id"]}))
            actions.append(Action(user_id, pair["id"], "replied", f"{len(text)} chars"))
    return actions


__all__ = [
    "ANSWER_MODES", "Action", "NotATestSetup", "TEST_POOL_PREFIX", "TEST_USER_PREFIX", "is_test_pool", "pair_and_ask", "persona_of",
    "play_once", "seeded_people", "setup_test_pool",
]
