"""Covers Omi asking how a plan went: when it is due, once only, in the app and on Telegram."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import storage
from agent.proactive import run_proactive_pass
from agent.proactive.away import follow_up_on_telegram
from agent.proactive.policy import due_event, event_follow_up_from, reach_out_hours
from realtime import realtime_hub

ZONE = ZoneInfo("Asia/Kolkata")
# 14:00 in Kolkata on Sun 20 Sep.
NOW = datetime(2026, 9, 20, 8, 30, tzinfo=UTC)
USER_ID = "event-user"
CONVERSATION_ID = "event-conversation"


def _local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=ZONE)


def _event(occurred: datetime, **overrides) -> dict:
    memory = {
        "id": "interview",
        "statement": "Has a job interview at a design studio.",
        "value": "job interview",
        "status": "active",
        "sensitivity": "standard",
        "allowed_uses": ["reply_context"],
        "occurred_at": occurred.isoformat(),
        "created_at": (occurred - timedelta(days=2)).isoformat(),
        "followed_up_at": None,
    }
    return {**memory, **overrides}


def test_timed_plan_is_asked_about_a_few_hours_later() -> None:
    assert event_follow_up_from(_local(20, 10), ZONE) == _local(20, 13)


def test_plan_with_no_time_of_day_is_asked_about_the_next_morning() -> None:
    assert event_follow_up_from(_local(19, 12), ZONE) == _local(20, 9)


def test_due_event_needs_the_time_to_have_come() -> None:
    assert due_event([_event(_local(20, 10))], NOW, ZONE)["id"] == "interview"
    assert due_event([_event(_local(20, 12, 30))], NOW, ZONE) is None


def test_due_event_skips_stale_told_after_asked_and_private_plans() -> None:
    occurred = _local(20, 10)
    skipped = [
        _event(_local(10, 10)),
        _event(occurred, created_at=(occurred + timedelta(hours=1)).isoformat()),
        _event(occurred, followed_up_at=_local(1, 10).isoformat()),
        _event(occurred, status="retracted"),
        _event(occurred, sensitivity="highly_sensitive"),
        _event(occurred, allowed_uses=["matching"]),
    ]
    for memory in skipped:
        assert due_event([memory], NOW, ZONE) is None, memory


def test_one_plan_follow_up_a_day() -> None:
    asked_today = _event(_local(19, 10), id="dinner", followed_up_at=_local(20, 9).isoformat())
    assert due_event([asked_today, _event(_local(20, 10))], NOW, ZONE) is None


def test_oldest_due_plan_comes_first() -> None:
    memories = [_event(_local(20, 10)), _event(_local(19, 18), id="dinner")]
    assert due_event(memories, NOW, ZONE)["id"] == "dinner"


def test_away_users_are_only_reached_in_their_daytime() -> None:
    assert reach_out_hours(NOW, ZONE)
    assert not reach_out_hours(_local(20, 23), ZONE)
    assert not reach_out_hours(_local(20, 7), ZONE)


def test_storage_marks_a_memory_followed_up() -> None:
    storage.reset_db()
    storage.save_conversation(
        {"id": CONVERSATION_ID, "status": "active", "messages": [{"role": "user", "content": "Interview on Sunday"}]},
        USER_ID,
    )
    memory = storage.create_agent_memory(
        {
            "user_id": USER_ID,
            "kind": "episodic",
            "purposes": ["personalization"],
            "key": "plan.interview",
            "value": "job interview",
            "confidence": 0.9,
            "importance": 0.6,
            "evidence": [{"conversation_id": CONVERSATION_ID, "message_index": 0, "exact_quote": "Interview on Sunday", "observed_at": "2026-09-18T10:00:00+00:00"}],
        }
    )
    assert memory["followed_up_at"] is None

    assert storage.mark_agent_memory_followed_up(memory["id"], USER_ID, NOW)
    assert not storage.mark_agent_memory_followed_up(memory["id"], "someone-else", NOW)

    stored = storage.get_agent_memory(memory["id"], USER_ID)
    assert stored["followed_up_at"].startswith("2026-09-20T08:30")


# The pass: an online user is asked in the app, an away user on Telegram.


def _seed(messages: list[dict], **conversation) -> None:
    storage.reset_db()
    storage.set_user_timezone(USER_ID, "Asia/Kolkata")
    storage.save_conversation(
        {"id": CONVERSATION_ID, "status": "active", "messages": messages, **conversation}, USER_ID
    )


def _msg(role: str, minutes_ago: float) -> dict:
    return {"role": role, "content": "x", "created_at": (NOW - timedelta(minutes=minutes_ago)).isoformat()}


class _Socket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


def _online_pass(memories: list[dict], reply: str) -> tuple[int, AsyncMock, list]:
    marked: list = []
    generate = AsyncMock(return_value=reply)

    async def scenario() -> int:
        await realtime_hub.reset()
        connection = await realtime_hub.register(_Socket(), USER_ID)
        await realtime_hub.subscribe(connection, "conversation", CONVERSATION_ID)
        with patch("agent.proactive.service.list_threads", return_value=[]), patch(
            "agent.proactive.service.list_agent_memories", return_value=memories
        ), patch(
            "agent.proactive.service.mark_agent_memory_followed_up",
            lambda memory_id, user_id, at: marked.append(memory_id),
        ), patch("agent.proactive.service._generate", generate):
            return await run_proactive_pass(now=NOW)

    return asyncio.run(scenario()), generate, marked


def test_online_user_is_asked_how_the_plan_went() -> None:
    _seed([_msg("user", 90), _msg("assistant", 89)])

    sent, generate, marked = _online_pass([_event(_local(20, 10))], "How did the interview go?")

    assert sent == 1
    instructions = generate.await_args.kwargs["instructions"]
    assert "Has a job interview at a design studio." in instructions
    assert "(today)" in instructions
    stored = storage.get_conversation(CONVERSATION_ID, USER_ID)["messages"][-1]
    assert stored["proactive_kind"] == "event_follow_up"
    assert stored["event_memory_id"] == "interview"
    assert marked == ["interview"]


def test_a_declined_plan_is_marked_so_it_is_weighed_once() -> None:
    _seed([_msg("user", 90), _msg("assistant", 89)])

    sent, _generate, marked = _online_pass([_event(_local(20, 10))], "")

    assert sent == 0
    assert marked == ["interview"]


def test_return_greeting_brings_up_the_plan() -> None:
    _seed([_msg("user", 3 * 24 * 60), _msg("assistant", 3 * 24 * 60 - 1)])

    sent, generate, marked = _online_pass([_event(_local(19, 12))], "Welcome back! How did the interview go?")

    assert sent == 1
    assert "Has a job interview" in generate.await_args.kwargs["instructions"]
    assert "(yesterday)" in generate.await_args.kwargs["instructions"]
    assert marked == ["interview"]


def _telegram_follow_up(now: datetime, reply: str = "How did the interview go?") -> tuple[bool, AsyncMock]:
    send = AsyncMock(return_value=True)
    with patch("agent.proactive.service.list_agent_memories", return_value=[_event(_local(20, 10))]), patch(
        "agent.proactive.service.mark_agent_memory_followed_up", lambda *args: None
    ), patch("agent.proactive.service._generate", AsyncMock(return_value=reply)), patch(
        "agent.proactive.away.send_telegram_message", send
    ):
        sent = asyncio.run(follow_up_on_telegram(USER_ID, "chat-1", now))
    return sent, send


def test_away_user_is_asked_on_telegram() -> None:
    _seed([_msg("user", 90), _msg("assistant", 89)], channel="telegram")

    sent, send = _telegram_follow_up(NOW)

    assert sent
    send.assert_awaited_once_with("chat-1", "How did the interview go?")
    stored = storage.get_conversation(CONVERSATION_ID, USER_ID)["messages"][-1]
    assert stored["proactive_kind"] == "event_follow_up"


def test_no_telegram_message_at_night_or_without_a_telegram_chat() -> None:
    _seed([_msg("user", 90), _msg("assistant", 89)], channel="telegram")
    assert _telegram_follow_up(_local(20, 22).astimezone(UTC))[0] is False

    _seed([_msg("user", 90), _msg("assistant", 89)])
    sent, send = _telegram_follow_up(NOW)
    assert not sent
    send.assert_not_awaited()
