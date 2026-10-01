"""Proof check: a second model call keeps only the messages that really show each vibe line."""

import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from agent.cognition.background.service import run_background_cognition
from agent.cognition.background.vibe_backfill import backfill_user_vibe
from agent.cognition.background.vibe_prompt import VIBE_VERIFY_SYSTEM_PROMPT
from agent.cognition.background.vibe_verify import verify_vibe_updates
from storage import get_vibe_card, reset_db, save_conversation

CONVERSATION_ID = "vibe-verify-chat"
USER_ID = "vibe-verify-user"
MESSAGES = [
    {"role": "user", "content": "I love long drives at night", "created_at": "2026-09-20T18:00:00+00:00"},
    {"role": "assistant", "content": "Night drives are the best.", "created_at": "2026-09-20T18:00:05+00:00"},
    {"role": "user", "content": "people who cancel last minute drive me mad", "created_at": "2026-09-21T18:00:00+00:00"},
]


def item(index: int) -> dict:
    return {"conversation_id": CONVERSATION_ID, "message_index": index}


UPDATES = {
    "interests": {"text": "Loves long night drives.", "evidence": [item(0)]},
    "deal_breakers": {"text": "Can't stand dishonest people.", "evidence": [item(0), item(2)]},
}


def quote(evidence: dict) -> str | None:
    message = MESSAGES[evidence["message_index"]]
    return message["content"] if message["role"] == "user" else None


class VerifyVibeUpdatesTest(unittest.IsolatedAsyncioTestCase):
    async def _verify(self, response: object) -> tuple[dict, dict]:
        with patch(
            "agent.cognition.background.vibe_verify.analyze_vibe_verification",
            new_callable=AsyncMock,
            return_value=response,
        ) as checker:
            result = await verify_vibe_updates(UPDATES, quote, conversation_id=CONVERSATION_ID)
        return result, json.loads(checker.await_args.args[0])

    async def test_keeps_only_the_proof_the_checker_confirms(self) -> None:
        result, payload = await self._verify({"interests": ["e1"], "deal_breakers": ["e3"]})

        self.assertEqual(result["interests"]["evidence"], [item(0)])
        self.assertEqual(result["deal_breakers"]["evidence"], [item(2)])
        self.assertEqual(result["deal_breakers"]["text"], "Can't stand dishonest people.")
        # The checker sees each line with only its own cited messages.
        lines = {line["area"]: line for line in payload["lines"]}
        self.assertEqual([m["text"] for m in lines["interests"]["messages"]], ["I love long drives at night"])
        self.assertEqual(len(lines["deal_breakers"]["messages"]), 2)

    async def test_a_line_without_confirmed_proof_is_dropped(self) -> None:
        result, _ = await self._verify({"interests": ["e1"], "deal_breakers": []})

        self.assertEqual(set(result), {"interests"})

    async def test_proof_cannot_move_to_another_line_or_area(self) -> None:
        # e1 belongs to interests; citing it for deal_breakers (or an unknown area) does nothing.
        result, _ = await self._verify({"deal_breakers": ["e1", "e9"], "humor": ["e1"]})

        self.assertEqual(result, {})

    async def test_bad_checker_output_keeps_nothing(self) -> None:
        for response in ("yes", None, [], {"interests": "e1"}):
            with self.subTest(response=response):
                result, _ = await self._verify(response)
                self.assertEqual(result, {})

    def test_prompt_judges_each_message_on_its_own(self) -> None:
        self.assertIn("read on its own, it directly shows", VIBE_VERIFY_SYSTEM_PROMPT)
        self.assertIn("One message rarely proves many different areas", VIBE_VERIFY_SYSTEM_PROMPT)


class VerifyModelTest(unittest.TestCase):
    def test_strong_default_on_deepinfra_and_env_override(self) -> None:
        from agent.providers.extraction.service import vibe_verify_model

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(vibe_verify_model("deepinfra"), "deepseek-ai/DeepSeek-V3.2")
            self.assertIsNone(vibe_verify_model("openai"))
        with patch.dict(os.environ, {"VIBE_VERIFY_MODEL": "some/model"}):
            self.assertEqual(vibe_verify_model("deepinfra"), "some/model")


class VerifiedWritesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": CONVERSATION_ID, "status": "active", "messages": MESSAGES}, USER_ID)
        self.env = patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    async def _background(self, checker: AsyncMock) -> None:
        response = {
            "decision": "no_change",
            "operations": [],
            "thread_operation": {"operation": "none"},
            "handoff": {"summary": "", "active_people": [], "active_topics": [], "unresolved_references": []},
            "vibe": {
                "interests": {"line": "Loves long night drives.", "evidence": [0]},
                "deal_breakers": {"line": "Can't stand dishonest people.", "evidence": [0]},
            },
        }
        with patch(
            "agent.cognition.background.service.analyze_background_cognition",
            new_callable=AsyncMock,
            return_value=response,
        ), patch("agent.cognition.background.vibe_verify.analyze_vibe_verification", checker), patch(
            "agent.cognition.background.service.realtime_hub.publish", new_callable=AsyncMock
        ):
            await run_background_cognition(CONVERSATION_ID, USER_ID, MESSAGES)

    async def test_background_saves_only_confirmed_lines_with_when_they_were_said(self) -> None:
        await self._background(AsyncMock(return_value={"interests": ["e1"], "deal_breakers": []}))

        areas = get_vibe_card(USER_ID)["areas"]
        self.assertEqual(set(areas), {"interests"})
        self.assertEqual(areas["interests"]["evidence"][0]["sent_at"], "2026-09-20T18:00:00+00:00")

    async def test_a_failed_check_saves_nothing(self) -> None:
        await self._background(AsyncMock(side_effect=TimeoutError("slow")))

        self.assertEqual(get_vibe_card(USER_ID)["areas"], {})

    async def test_backfill_drops_lines_the_check_rejects(self) -> None:
        backfill = {"vibe": {"deal_breakers": {"line": "Can't stand dishonest people.", "evidence": ["m1"]}}}
        with patch(
            "agent.cognition.background.vibe_backfill.analyze_vibe_backfill",
            new_callable=AsyncMock,
            return_value=backfill,
        ), patch(
            "agent.cognition.background.vibe_verify.analyze_vibe_verification",
            new_callable=AsyncMock,
            return_value={"deal_breakers": []},
        ):
            result = await backfill_user_vibe(USER_ID, apply=True)

        self.assertEqual(result["status"], "nothing_found")
        self.assertEqual(get_vibe_card(USER_ID)["areas"], {})


if __name__ == "__main__":
    unittest.main()
