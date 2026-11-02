"""Sending while Omi writes: quick messages share one reply, and none is ever left unanswered."""

import asyncio
import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx

from agent.runtime.orchestrator import AgentTurnResult, _read_together
from api.burst_window import max_wait_seconds, quiet_seconds, seconds_left
from api.chat_service import WEB_CHANNEL
from api.main import app, current_user
from security.auth import CurrentUser
from storage import (
    burst_open,
    burst_state,
    get_conversation,
    join_burst,
    list_user_app_events,
    release_burst,
    renew_burst,
    reset_db,
    touch_burst,
)

USER_ID = "burst-user"
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


class _Turn:
    def __init__(self, delays: tuple[float, ...] = ()) -> None:
        self.calls: list[dict] = []
        self.delays = delays

    async def __call__(self, **kwargs) -> AgentTurnResult:
        index = len(self.calls)
        self.calls.append(kwargs)
        await asyncio.sleep(self.delays[index] if index < len(self.delays) else 0)
        user_message = {"role": "user", "content": kwargs["user_text"]}
        reply = {"role": "assistant", "content": f"reply {index + 1}"}
        return AgentTurnResult(messages=[*kwargs["messages"], user_message, reply], quality_valid=True)


class BurstWindowTest(unittest.TestCase):
    def test_the_wait_grows_with_the_burst(self) -> None:
        with patch.dict(os.environ, {"CHAT_BURST_QUIET_SECONDS": "1.5"}):
            self.assertEqual([quiet_seconds(count) for count in (1, 2, 3, 4, 30)], [1.5, 2.25, 2.25, 3.0, 3.0])
        self.assertLess(max_wait_seconds(3), max_wait_seconds(4))

    def test_a_new_message_starts_the_wait_again_up_to_the_max(self) -> None:
        with patch.dict(os.environ, {"CHAT_BURST_QUIET_SECONDS": "1.5"}):
            self.assertEqual(seconds_left(1, NOW, NOW, NOW), 1.5)
            self.assertEqual(seconds_left(1, NOW, NOW, NOW + timedelta(seconds=2)), -0.5)
            # Still writing after the max: Omi answers anyway.
            started = NOW - timedelta(seconds=6)
            self.assertEqual(seconds_left(2, NOW, started, NOW), 0)
            started = NOW - timedelta(seconds=15)
            self.assertEqual(seconds_left(10, NOW, started, NOW), 0)

    def test_a_bad_setting_falls_back(self) -> None:
        with patch.dict(os.environ, {"CHAT_BURST_QUIET_SECONDS": "soon"}):
            self.assertEqual(quiet_seconds(1), 1.5)


class BurstStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()

    def test_an_open_burst_is_one_with_a_live_lease(self) -> None:
        self.assertFalse(burst_open("web", "c", NOW))
        token = join_burst("web", "c", "c", now=NOW, lease_seconds=60)["token"]
        self.assertTrue(burst_open("web", "c", NOW))
        self.assertFalse(burst_open("web", "c", NOW + timedelta(seconds=61)))

        self.assertTrue(renew_burst("web", "c", token, until=NOW + timedelta(seconds=120)))
        self.assertTrue(burst_open("web", "c", NOW + timedelta(seconds=61)))
        self.assertFalse(renew_burst("web", "c", "someone-else", until=NOW))

    def test_typing_moves_the_quiet_wait_but_counts_no_message(self) -> None:
        touch_burst("web", "c", NOW)  # no burst: nothing happens
        self.assertIsNone(burst_state("web", "c"))
        join_burst("web", "c", "c", now=NOW, lease_seconds=60)
        later = NOW + timedelta(seconds=3)
        touch_burst("web", "c", later)
        state = burst_state("web", "c")
        self.assertEqual((state["arrivals"], state["last_at"]), (1, later))

    def test_a_dead_repliers_lease_is_taken_over(self) -> None:
        first = join_burst("web", "c", "c", now=NOW, lease_seconds=60)["token"]
        self.assertIsNone(join_burst("web", "c", "c", now=NOW + timedelta(seconds=1), lease_seconds=60)["token"])
        second = join_burst("web", "c", "c", now=NOW + timedelta(seconds=61), lease_seconds=60)["token"]
        self.assertNotIn(second, (None, first))
        release_burst("web", "c", first)  # the old replier can no longer close it
        self.assertEqual(burst_state("web", "c")["token"], second)


class ReadTogetherTest(unittest.TestCase):
    def test_recall_reads_the_whole_burst(self) -> None:
        messages = [{"role": "assistant", "content": "hey"}, {"role": "user", "content": "went to goa"}, {"role": "user", "content": "with riya"}]
        self.assertEqual(_read_together(messages, "it was awesome", 3), "went to goa\nwith riya\nit was awesome")
        self.assertEqual(_read_together(messages, "it was awesome", 1), "it was awesome")

    def test_a_long_burst_is_read_by_its_end(self) -> None:
        messages = [{"role": "user", "content": f"m{index}"} for index in range(50)]
        self.assertEqual(_read_together(messages, "last", 51).split("\n"), ["m45", "m46", "m47", "m48", "m49", "last"])


class WebBurstTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {"AUTH_REQUIRED": "false", "AGENT_PROVIDER": "mock", "DATA_POINT_EXTRACTOR": "rules",
             "AGENT_PIPELINE_VERSION": "v1", "AGENT_ROLLOUT": "off", "PROACTIVE_MESSAGING_ENABLED": "false",
             "USER_CHAT_MONTHLY_LIMIT": "300"},
        )
        self.env.start()
        app.dependency_overrides.clear()

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id=USER_ID, email="burst@example.com", display_name="Burst User")

        app.dependency_overrides[current_user] = signed_in_user
        reset_db()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.env.stop()

    async def _send_all(self, texts: list[str], gap: float = 0, offsets: tuple[float, ...] = (), **extra) -> tuple[str, list[httpx.Response]]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            conversation_id = (await client.post("/api/agent/conversations")).json()["id"]

            async def send(index: int, text: str) -> httpx.Response:
                await asyncio.sleep(offsets[index] if offsets else index * gap)
                return await client.post(
                    f"/api/agent/conversations/{conversation_id}/messages", json={"message": text, **extra}
                )

            responses = await asyncio.gather(*(send(index, text) for index, text in enumerate(texts)))
        return conversation_id, list(responses)

    def _contents(self, conversation_id: str) -> list[str]:
        return [m["content"] for m in get_conversation(conversation_id, USER_ID)["messages"][1:]]

    def _quota_events(self) -> int:
        return sum(1 for event in list_user_app_events(USER_ID) if event["event_name"] == "quota.chat_message")

    def test_quick_messages_share_one_reply_and_one_quota_count(self) -> None:
        turn = _Turn()
        with patch.dict(os.environ, {"CHAT_BURST_QUIET_SECONDS": "0.2"}), patch("api.main.run_agent_turn", turn):
            conversation_id, responses = asyncio.run(self._send_all(["hey", "listen", "I got the job!"], gap=0.03))

        self.assertEqual([response.status_code for response in responses], [200, 200, 200])
        self.assertEqual(len(turn.calls), 1)
        self.assertEqual(turn.calls[0]["unanswered_count"], 3)
        self.assertEqual(self._contents(conversation_id), ["hey", "listen", "I got the job!", "reply 1"])
        self.assertEqual(self._quota_events(), 1)
        # The first request carries the reply; the others return as soon as they are saved.
        self.assertEqual(responses[0].json()["messages"][-1]["content"], "reply 1")
        self.assertEqual(responses[1].json()["messages"][-1]["role"], "user")

    def test_a_flood_is_never_stopped_by_the_per_minute_limit(self) -> None:
        turn = _Turn()
        texts = [f"message {index}" for index in range(25)]
        with patch.dict(os.environ, {"CHAT_BURST_QUIET_SECONDS": "0.2"}), patch("api.main.run_agent_turn", turn):
            conversation_id, responses = asyncio.run(self._send_all(texts, gap=0.01))

        self.assertEqual({response.status_code for response in responses}, {200})
        self.assertEqual(len(turn.calls), 1)
        self.assertEqual(turn.calls[0]["unanswered_count"], 25)
        self.assertEqual(self._contents(conversation_id)[-1], "reply 1")

    def test_a_script_is_stopped_by_the_quick_message_cap(self) -> None:
        turn = _Turn(delays=(0.5,))
        with patch.dict(os.environ, {"USER_CHAT_QUICK_MESSAGES_PER_MINUTE": "2"}), patch("api.main.run_agent_turn", turn):
            _conversation_id, responses = asyncio.run(self._send_all(["a", "b", "c", "d"], gap=0.05))

        self.assertEqual([response.status_code for response in responses], [200, 200, 200, 429])

    def test_messages_spaced_apart_get_their_own_replies(self) -> None:
        turn = _Turn()
        with patch("api.main.run_agent_turn", turn):
            conversation_id, _responses = asyncio.run(self._send_all(["hi", "second thought"], gap=0.1))

        self.assertEqual(self._contents(conversation_id), ["hi", "reply 1", "second thought", "reply 2"])
        self.assertEqual(self._quota_events(), 2)

    def test_a_message_after_the_last_restart_still_gets_a_reply(self) -> None:
        # Each draft is overtaken by a new message until the restarts run out. The last message then
        # comes in during a draft that gets saved: it must stay unanswered and get its own reply.
        turn = _Turn(delays=(0.2, 0.2, 0.2))
        with patch("api.main.run_agent_turn", turn):
            conversation_id, responses = asyncio.run(self._send_all(["a", "b", "c", "d"], offsets=(0, 0.1, 0.3, 0.5)))

        self.assertEqual({response.status_code for response in responses}, {200})
        messages = get_conversation(conversation_id, USER_ID)["messages"][1:]
        self.assertEqual([m["content"] for m in messages], ["a", "b", "c", "reply 3", "d", "reply 4"])
        self.assertTrue(all(m["delivery_status"] == "read" for m in messages if m["role"] == "user"))
        self.assertNotIn("unanswered_count", turn.calls[3])
        # Three drafts for the first reply count once; the second reply counts once more.
        self.assertEqual(self._quota_events(), 2)

    def test_a_failed_reply_marks_the_whole_burst_and_retry_answers_it(self) -> None:
        class _Failing(_Turn):
            async def __call__(inner, **kwargs):
                raise RuntimeError("model down")

        with patch.dict(os.environ, {"CHAT_BURST_QUIET_SECONDS": "0.2"}), patch("api.main.run_agent_turn", _Failing()):
            conversation_id, responses = asyncio.run(self._send_all(["hey", "you there?"], gap=0.02))

        self.assertEqual(sorted(response.status_code for response in responses), [200, 502])
        failed = next(response for response in responses if response.status_code == 502)
        self.assertEqual(failed.json()["detail"]["code"], "reply_failed")
        self.assertEqual(failed.json()["detail"]["message_index"], 2)
        messages = get_conversation(conversation_id, USER_ID)["messages"]
        self.assertEqual([m["delivery_status"] for m in messages[1:]], ["failed", "failed"])

        turn = _Turn()

        async def retry() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post(f"/api/agent/conversations/{conversation_id}/messages/2/retry")

        with patch("api.main.run_agent_turn", turn):
            response = asyncio.run(retry())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(turn.calls[0]["unanswered_count"], 2)
        messages = get_conversation(conversation_id, USER_ID)["messages"][1:]
        self.assertEqual([m["delivery_status"] for m in messages[:2]], ["read", "read"])
        self.assertEqual(messages[-1]["content"], "reply 1")

    def test_a_send_retried_with_the_same_client_id_is_saved_once(self) -> None:
        with patch("api.main.run_agent_turn", _Turn()):
            conversation_id, _ = asyncio.run(self._send_all(["hi", "hi"], gap=0.05, client_id="send-1"))

        contents = self._contents(conversation_id)
        self.assertEqual(contents.count("hi"), 1)
        self.assertEqual(get_conversation(conversation_id, USER_ID)["messages"][1]["client_id"], "send-1")

    def test_typing_endpoint_needs_the_users_own_chat(self) -> None:
        async def scenario() -> tuple[int, int]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                own = (await client.post("/api/agent/conversations")).json()["id"]
                ok = await client.post(f"/api/agent/conversations/{own}/typing")
                missing = await client.post("/api/agent/conversations/not-mine/typing")
            return ok.status_code, missing.status_code

        self.assertEqual(asyncio.run(scenario()), (200, 404))
        self.assertEqual(WEB_CHANNEL, "web")
