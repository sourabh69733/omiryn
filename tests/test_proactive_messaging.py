"""Covers when the agent may open a conversation on its own, and that it stays polite."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import storage
from agent.context_engine.conversation_engine.state.models import ConversationThread
from agent.proactive import nudge_block_reason, pick_thread, run_proactive_pass
from realtime import realtime_hub

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
USER_ID = "proactive-user"
CONVERSATION_ID = "proactive-conversation"


def _msg(role: str, minutes_ago: float, *, proactive: bool = False) -> dict:
    message = {"role": role, "content": "x", "created_at": (NOW - timedelta(minutes=minutes_ago)).isoformat()}
    if proactive:
        message["proactive"] = True
    return message


def _thread(**overrides) -> ConversationThread:
    values = dict(
        id="t1", user_id=USER_ID, created_in_conversation_id="c", last_conversation_id="c",
        title="Riya", summary="Riya keeps calling", origin="user", next_angle="ask how it felt",
    )
    return ConversationThread(**{**values, **overrides})


def test_allows_a_nudge_after_silence() -> None:
    assert nudge_block_reason([_msg("user", 90), _msg("assistant", 89)], NOW) is None


def test_min_silence_can_be_shortened_for_testing(monkeypatch) -> None:
    monkeypatch.setenv("PROACTIVE_MIN_SILENCE_SECONDS", "60")

    assert nudge_block_reason([_msg("user", 5)], NOW) is None
    assert nudge_block_reason([_msg("user", 0.5)], NOW) == "recently_active"


def test_blocks_when_user_was_just_active() -> None:
    assert nudge_block_reason([_msg("user", 5)], NOW) == "recently_active"


def test_blocks_before_the_user_has_ever_spoken() -> None:
    assert nudge_block_reason([_msg("assistant", 120)], NOW) == "no_user_message"


def test_stays_quiet_until_the_user_answers_the_last_nudge() -> None:
    messages = [_msg("user", 300), _msg("assistant", 200, proactive=True)]
    assert nudge_block_reason(messages, NOW) == "last_nudge_unanswered"


def test_allows_a_second_nudge_after_the_user_replied_then_caps_at_two() -> None:
    answered = [
        _msg("user", 400),
        _msg("assistant", 300, proactive=True),
        _msg("user", 200),
    ]
    assert nudge_block_reason(answered, NOW) is None
    capped = [*answered, _msg("assistant", 100, proactive=True), _msg("user", 60)]
    assert nudge_block_reason(capped, NOW) == "daily_limit"


def test_old_nudges_do_not_count_toward_the_daily_cap() -> None:
    day_old = [
        _msg("user", 3000),
        _msg("assistant", 2900, proactive=True),
        _msg("user", 2800),
        _msg("assistant", 2700, proactive=True),
        _msg("user", 120),
    ]
    assert nudge_block_reason(day_old, NOW) is None


def test_thread_pick_skips_paused_low_interest_and_angleless() -> None:
    threads = [
        _thread(id="paused", status="paused", salience=0.99),
        _thread(id="cool", user_interest="low", salience=0.98),
        _thread(id="noangle", next_angle=None, salience=0.97),
        _thread(id="ok", salience=0.6),
        _thread(id="better", salience=0.8),
    ]
    assert pick_thread(threads).id == "better"
    assert pick_thread(threads[:3]) is None


class _Socket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


def _seed(messages: list[dict]) -> _Socket:
    storage.reset_db()
    storage.save_conversation(
        {"id": CONVERSATION_ID, "status": "active", "messages": messages}, USER_ID
    )
    return _Socket()


async def _connect(socket: _Socket) -> None:
    await realtime_hub.reset()
    connection = await realtime_hub.register(socket, USER_ID)
    await realtime_hub.subscribe(connection, "conversation", CONVERSATION_ID)


def _run_pass(socket: _Socket, *, reply: str = "Hey, how did the Riya call go?") -> int:
    async def scenario() -> int:
        await _connect(socket)
        with patch("agent.proactive.service.list_threads", return_value=[_thread()]), patch(
            "agent.proactive.service._generate", AsyncMock(return_value=reply)
        ):
            return await run_proactive_pass(now=NOW)

    return asyncio.run(scenario())


def test_pass_saves_and_pushes_one_proactive_message() -> None:
    socket = _seed([_msg("user", 90), _msg("assistant", 89)])

    assert _run_pass(socket) == 1

    stored = storage.get_conversation(CONVERSATION_ID, USER_ID)["messages"]
    assert stored[-1]["proactive"] is True
    assert stored[-1]["content"] == "Hey, how did the Riya call go?"
    assert socket.sent[-1]["type"] == "message.created"


def test_pass_respects_the_users_off_switch() -> None:
    socket = _seed([_msg("user", 90), _msg("assistant", 89)])
    storage.set_proactive_enabled(USER_ID, False)

    assert _run_pass(socket) == 0
    assert socket.sent == []


def test_pass_does_nothing_when_the_user_is_not_watching() -> None:
    _seed([_msg("user", 90), _msg("assistant", 89)])

    async def scenario() -> int:
        await realtime_hub.reset()
        return await run_proactive_pass(now=NOW)

    assert asyncio.run(scenario()) == 0


def test_pass_does_not_talk_over_a_message_sent_while_generating() -> None:
    socket = _seed([_msg("user", 90), _msg("assistant", 89)])

    async def slow_reply(*_args, **_kwargs) -> str:
        storage.save_conversation(
            {
                "id": CONVERSATION_ID,
                "status": "active",
                "messages": [_msg("user", 90), _msg("assistant", 89), _msg("user", 0)],
            },
            USER_ID,
        )
        return "Too late"

    async def scenario() -> int:
        await _connect(socket)
        with patch("agent.proactive.service.list_threads", return_value=[_thread()]), patch(
            "agent.proactive.service._generate", slow_reply
        ):
            return await run_proactive_pass(now=NOW)

    assert asyncio.run(scenario()) == 0
    assert len(storage.get_conversation(CONVERSATION_ID, USER_ID)["messages"]) == 3
