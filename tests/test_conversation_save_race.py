"""Two writers on one chat at the same time never lose each other's messages.

Every message change goes through `update_conversation`, which reads the newest stored list
under a row lock and adds to it. A reply drafted from an older copy, a nudge, or a second
message sent while Omi writes, all land; nothing is overwritten.
"""

import asyncio
import os
import unittest
from unittest.mock import patch

import httpx

from agent.runtime.orchestrator import AgentTurnResult
from api.main import app, current_user
from security.auth import CurrentUser
from storage import get_conversation, reset_db, save_conversation, update_conversation

USER_ID = "race-user"


class _SlowFirstTurn:
    """The first reply takes a while; later ones are quick."""

    def __init__(self, first_delay: float) -> None:
        self.calls: list[dict] = []
        self.first_delay = first_delay

    async def __call__(self, **kwargs) -> AgentTurnResult:
        self.calls.append(kwargs)
        await asyncio.sleep(self.first_delay if len(self.calls) == 1 else 0)
        user_message = {"role": "user", "content": kwargs["user_text"]}
        reply = {"role": "assistant", "content": f"reply to {kwargs['user_text']}"}
        return AgentTurnResult(messages=[*kwargs["messages"], user_message, reply], quality_valid=True)


class UpdateConversationTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": "chat-1", "status": "active", "messages": [{"role": "user", "content": "hi"}]}, USER_ID)

    def test_a_change_made_from_an_old_copy_keeps_what_was_saved_meanwhile(self) -> None:
        old_copy = get_conversation("chat-1", USER_ID)["messages"]
        update_conversation("chat-1", USER_ID, lambda messages: [*messages, {"role": "user", "content": "wait"}])

        # A reply drafted from the old copy is appended after everything stored now.
        stored = update_conversation(
            "chat-1", USER_ID, lambda messages: [*messages, {"role": "assistant", "content": f"reply to {old_copy[-1]['content']}"}]
        )

        self.assertEqual([m["content"] for m in stored["messages"]], ["hi", "wait", "reply to hi"])
        self.assertEqual([m["content"] for m in get_conversation("chat-1", USER_ID)["messages"]], ["hi", "wait", "reply to hi"])

    def test_returning_none_leaves_the_messages_and_sets_only_fields(self) -> None:
        stored = update_conversation("chat-1", USER_ID, lambda messages: None, fields={"agent_voice": "female"})

        self.assertEqual(stored["agent_voice"], "female")
        self.assertEqual(len(stored["messages"]), 1)
        self.assertEqual(get_conversation("chat-1", USER_ID)["agent_voice"], "female")

    def test_someone_elses_chat_is_not_changed(self) -> None:
        self.assertIsNone(update_conversation("chat-1", "other-user", lambda messages: []))
        self.assertEqual(len(get_conversation("chat-1", USER_ID)["messages"]), 1)


class WebReplyRaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {"AUTH_REQUIRED": "false", "AGENT_PROVIDER": "mock", "DATA_POINT_EXTRACTOR": "rules",
             "AGENT_PIPELINE_VERSION": "v1", "AGENT_ROLLOUT": "off", "PROACTIVE_MESSAGING_ENABLED": "false"},
        )
        self.env.start()
        app.dependency_overrides.clear()

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id=USER_ID, email="race@example.com", display_name="Race User")

        app.dependency_overrides[current_user] = signed_in_user
        reset_db()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.env.stop()

    async def _send_all(self, texts: list[str], gap: float) -> tuple[str, list[httpx.Response]]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            conversation_id = (await client.post("/api/agent/conversations")).json()["id"]

            async def send(index: int, text: str) -> httpx.Response:
                await asyncio.sleep(index * gap)
                return await client.post(f"/api/agent/conversations/{conversation_id}/messages", json={"message": text})

            responses = await asyncio.gather(*(send(index, text) for index, text in enumerate(texts)))
        return conversation_id, list(responses)

    def test_a_message_sent_while_omi_replies_is_not_lost(self) -> None:
        turn = _SlowFirstTurn(first_delay=0.3)
        with patch("api.main.run_agent_turn", turn):
            conversation_id, responses = asyncio.run(self._send_all(["hi", "wait"], gap=0.1))

        self.assertEqual([response.status_code for response in responses], [200, 200])
        contents = [m["content"] for m in get_conversation(conversation_id, USER_ID)["messages"][1:]]
        # "wait" and its reply were saved while "hi" was still being answered; all four are kept.
        self.assertEqual(sorted(contents), sorted(["hi", "wait", "reply to hi", "reply to wait"]))
        self.assertEqual(contents[:2], ["hi", "wait"])
        self.assertTrue(all(m["delivery_status"] == "read" for m in get_conversation(conversation_id, USER_ID)["messages"] if m["role"] == "user"))

    def test_a_nudge_that_lands_while_omi_replies_is_kept(self) -> None:
        from agent.proactive.service import deliver_messages

        class _TurnWithNudge(_SlowFirstTurn):
            async def __call__(inner, **kwargs) -> AgentTurnResult:
                delivered = await deliver_messages(
                    USER_ID,
                    kwargs["conversation_id"],
                    expected_count=len(kwargs["messages"]) + 1,
                    new_messages=[{"role": "assistant", "content": "nudge", "proactive": True, "created_at": "2026-10-29T10:00:00+00:00"}],
                )
                assert delivered
                return await super().__call__(**kwargs)

        with patch("api.main.run_agent_turn", _TurnWithNudge(first_delay=0)):
            conversation_id, responses = asyncio.run(self._send_all(["hi"], gap=0))

        self.assertEqual(responses[0].status_code, 200)
        contents = [m["content"] for m in get_conversation(conversation_id, USER_ID)["messages"][1:]]
        self.assertEqual(contents, ["hi", "nudge", "reply to hi"])
