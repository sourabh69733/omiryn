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


def test_thread_pick_never_repeats_a_thread_already_nudged() -> None:
    threads = [_thread(id="a", salience=0.9), _thread(id="b", salience=0.5)]

    assert pick_thread(threads, exclude_ids={"a"}).id == "b"
    assert pick_thread(threads, exclude_ids={"a", "b"}) is None


def test_model_can_decline_to_speak() -> None:
    from agent.proactive.service import _is_skip

    assert _is_skip("SKIP") and _is_skip(" skip. ") and _is_skip('"SKIP"')
    assert not _is_skip("Skip the boring part, how did the call go?")


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


# Return greetings: a user who opens the chat after a long gap gets one short hello.

from agent.proactive import greet_on_return, return_greeting_block_reason  # noqa: E402
from agent.proactive import service as proactive_service  # noqa: E402

HOUR = 60


def test_return_greeting_needs_a_long_gap() -> None:
    assert return_greeting_block_reason([_msg("user", 5 * HOUR)], NOW) == "no_long_gap"
    assert return_greeting_block_reason([_msg("user", 7 * HOUR)], NOW) is None
    assert return_greeting_block_reason([_msg("assistant", 7 * HOUR)], NOW) == "no_user_message"


def test_one_greeting_per_return() -> None:
    greeted = [_msg("user", 30 * HOUR), _msg("assistant", 7 * HOUR, proactive=True)]
    assert return_greeting_block_reason(greeted, NOW) == "last_nudge_unanswered"


def _greet(socket: _Socket, reply: str = "Morning! Big day, the interview is today.") -> tuple[bool, AsyncMock]:
    generate = AsyncMock(return_value=reply)

    async def scenario() -> bool:
        await _connect(socket)
        with patch("agent.proactive.service._generate", generate):
            return await greet_on_return(USER_ID, CONVERSATION_ID, NOW)

    return asyncio.run(scenario()), generate


def test_greeting_is_saved_pushed_and_tells_the_model_the_gap_and_hour() -> None:
    socket = _seed([_msg("user", 2 * 24 * HOUR + 1), _msg("assistant", 2 * 24 * HOUR)])
    storage.set_user_timezone(USER_ID, "Asia/Kolkata")

    sent, generate = _greet(socket)

    assert sent
    stored = storage.get_conversation(CONVERSATION_ID, USER_ID)["messages"][-1]
    assert stored["proactive"] is True and stored["proactive_kind"] == "return_greeting"
    assert socket.sent[-1]["type"] == "message.created"
    instructions = generate.await_args.kwargs["instructions"]
    assert "after 2 days away" in instructions
    assert "It is evening for them" in instructions  # 12:00 UTC is 5:30 pm in India


def test_no_greeting_when_the_user_was_here_recently_or_is_opted_out() -> None:
    socket = _seed([_msg("user", 60), _msg("assistant", 59)])
    assert _greet(socket)[0] is False
    socket = _seed([_msg("user", 2 * 24 * HOUR)])
    storage.set_proactive_enabled(USER_ID, False)
    assert _greet(socket)[0] is False


def test_periodic_pass_greets_a_returning_user_instead_of_a_topic_nudge() -> None:
    socket = _seed([_msg("user", 2 * 24 * HOUR), _msg("assistant", 2 * 24 * HOUR - 1)])
    generate = AsyncMock(return_value="Hey, welcome back!")

    async def scenario() -> int:
        await _connect(socket)
        with patch("agent.proactive.service.list_threads", return_value=[_thread()]), patch(
            "agent.proactive.service._generate", generate
        ):
            return await run_proactive_pass(now=NOW)

    assert asyncio.run(scenario()) == 1
    assert generate.await_args.kwargs["cue"] == proactive_service._RETURN_CUE


def test_scheduled_greeting_waits_and_skips_when_the_user_left(monkeypatch) -> None:
    monkeypatch.setenv("PROACTIVE_RETURN_GREETING_DELAY_SECONDS", "0")
    _seed([_msg("user", 2 * 24 * HOUR)])
    greet = AsyncMock(return_value=True)

    async def scenario(watching: bool) -> None:
        await realtime_hub.reset()
        if watching:
            await _connect(_Socket())
        with patch("agent.proactive.service.greet_on_return", greet):
            proactive_service.schedule_return_greeting(USER_ID, CONVERSATION_ID)
            proactive_service.schedule_return_greeting(USER_ID, CONVERSATION_ID)  # deduped
            await asyncio.gather(*proactive_service._greeting_tasks)

    asyncio.run(scenario(watching=False))
    assert greet.await_count == 0
    asyncio.run(scenario(watching=True))
    assert greet.await_count == 1


# Promise follow-ups: a due promise is raised once, then marked done.

from agent.proactive.policy import due_promise  # noqa: E402


def _promise(note_id: str, due_minutes_ago: float | None) -> dict:
    due = None if due_minutes_ago is None else (NOW - timedelta(minutes=due_minutes_ago)).isoformat()
    return {"id": note_id, "kind": "promise", "text": f"Ask about {note_id}.", "due_at": due}


def test_due_promise_picks_the_oldest_due_and_skips_future_and_stale() -> None:
    notes = [
        _promise("future", -60),
        _promise("recent", 30),
        _promise("older", 3 * 24 * HOUR),
        _promise("stale", 15 * 24 * HOUR),
        _promise("undated", None),
        {"id": "opinion", "kind": "opinion", "text": "x", "due_at": None},
    ]
    assert due_promise(notes, NOW)["id"] == "older"
    assert due_promise(notes[:1], NOW) is None


def _save_promise(due_minutes_ago: float) -> None:
    storage.add_self_notes(
        USER_ID,
        CONVERSATION_ID,
        [
            {
                "id": "interview",
                "kind": "promise",
                "text": "Ask how the interview went.",
                "message_index": 1,
                "due_at": NOW - timedelta(minutes=due_minutes_ago),
            }
        ],
    )


def test_online_user_gets_a_promise_follow_up_before_any_topic_nudge() -> None:
    socket = _seed([_msg("user", 90), _msg("assistant", 89)])
    _save_promise(10)
    generate = AsyncMock(return_value="So, how did the interview go?")

    async def scenario() -> int:
        await _connect(socket)
        with patch("agent.proactive.service.list_threads", return_value=[_thread()]), patch(
            "agent.proactive.service._generate", generate
        ):
            first = await run_proactive_pass(now=NOW)
            second = await run_proactive_pass(now=NOW)  # last message unanswered: quiet
            return first + second

    assert asyncio.run(scenario()) == 1
    assert "Ask how the interview went." in generate.await_args.kwargs["instructions"]
    stored = storage.get_conversation(CONVERSATION_ID, USER_ID)["messages"][-1]
    assert stored["proactive_kind"] == "promise_follow_up"
    assert stored["promise_note_id"] == "interview"
    assert storage.list_active_self_notes(USER_ID) == []


def test_return_greeting_brings_up_the_due_promise_and_keeps_it() -> None:
    socket = _seed([_msg("user", 2 * 24 * HOUR + 1), _msg("assistant", 2 * 24 * HOUR)])
    _save_promise(60)

    sent, generate = _greet(socket)

    assert sent
    assert "Ask how the interview went." in generate.await_args.kwargs["instructions"]
    assert storage.list_active_self_notes(USER_ID) == []


def test_promise_stays_open_when_the_message_was_not_delivered() -> None:
    socket = _seed([_msg("user", 2 * 24 * HOUR + 1), _msg("assistant", 2 * 24 * HOUR)])
    _save_promise(60)

    sent, _generate = _greet(socket, reply="")

    assert not sent
    assert [note["id"] for note in storage.list_active_self_notes(USER_ID)] == ["interview"]


# Typing: the chat shows dots while the companion writes a message of its own.


def _event_types(socket: _Socket) -> list[tuple[str, object]]:
    return [(event["type"], event["payload"].get("active")) for event in socket.sent]


def test_greeting_is_announced_with_typing_dots() -> None:
    socket = _seed([_msg("user", 2 * 24 * HOUR + 1), _msg("assistant", 2 * 24 * HOUR)])

    async def scenario() -> bool:
        await _connect(socket)
        with patch("agent.proactive.service._initiative_text", AsyncMock(return_value="Hey, welcome back!")):
            return await greet_on_return(USER_ID, CONVERSATION_ID, NOW)

    assert asyncio.run(scenario())
    assert _event_types(socket) == [("agent.typing", True), ("agent.typing", False), ("message.created", None)]


def test_topic_nudges_that_may_be_skipped_show_no_typing() -> None:
    socket = _seed([_msg("user", 90), _msg("assistant", 89)])

    async def scenario() -> int:
        await _connect(socket)
        with patch("agent.proactive.service.list_threads", return_value=[_thread()]), patch(
            "agent.proactive.service._initiative_text", AsyncMock(return_value="SKIP")
        ):
            return await run_proactive_pass(now=NOW)

    assert asyncio.run(scenario()) == 0
    assert socket.sent == []
