"""One neutral companion; its voice follows the user's wish, in settings or in chat."""

import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agent.context_engine.conversation_engine.policy.replies import strip_voice_marker
from agent.context_engine.engine import build_model_context_package
from agent.runtime.orchestrator import run_agent_turn
from api.main import app, current_user
from security.auth import CurrentUser
from storage import get_conversation, reset_db, save_conversation

USER_ID = "voice-user"


def _prompt(conversation_id: str = "c") -> str:
    with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"}):
        return build_model_context_package(
            conversation_id=conversation_id, user_text="kya chal raha hai", user_id=USER_ID,
            user_profile={"interested_in": "women"}, model=None, agent_tone="auto", agent_name=None,
            style_source_id=None, user_message_index=0, assistant_message_index=1,
        ).system_prompt


class VoicePromptTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()

    def test_default_voice_is_neutral_whoever_the_user_wants_to_meet(self) -> None:
        save_conversation({"id": "c", "status": "active", "messages": []}, USER_ID)
        prompt = _prompt()
        self.assertIn("Voice: gender-neutral", prompt)
        self.assertIn("mujhe lagta hai", prompt)
        self.assertIn("gender-neutral AI companion", prompt)

    def test_chosen_voice_changes_grammar_not_identity(self) -> None:
        save_conversation({"id": "c", "status": "active", "messages": [], "agent_voice": "female"}, USER_ID)
        prompt = _prompt()
        self.assertIn("Voice: feminine", prompt)
        self.assertIn("you are still an AI", prompt)

    def test_old_chats_keep_the_voice_their_name_implied(self) -> None:
        save_conversation({"id": "c", "status": "active", "messages": [], "agent_name": "Kabir"}, USER_ID)
        self.assertEqual(get_conversation("c", USER_ID)["agent_voice"], "male")


class VoiceMarkerTest(unittest.TestCase):
    def test_marker_is_found_and_hidden(self) -> None:
        self.assertEqual(strip_voice_marker("<voice:female>Theek hai, ab aise baat karti hoon"),
                         ("Theek hai, ab aise baat karti hoon", "female"))
        self.assertEqual(strip_voice_marker("[VOICE: Male] done"), ("done", "male"))
        self.assertEqual(strip_voice_marker("no change"), ("no change", None))


class VoiceTurnTest(unittest.IsolatedAsyncioTestCase):
    async def test_asking_in_chat_switches_the_voice(self) -> None:
        reset_db()
        save_conversation({"id": "c", "status": "active", "messages": []}, USER_ID)
        reply = AsyncMock(return_value="<voice:female>Theek hai, ab aise baat karti hoon")
        with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"}), patch(
            "agent.runtime.orchestrator.generate_agent_reply", reply
        ):
            result = await run_agent_turn(
                conversation_id="c", messages=[], user_text="ladki ki tarah baat karo na", user_id=USER_ID,
                user_profile={}, model=None, agent_mode="know_me", agent_tone="auto", style_source_id=None,
            )
        self.assertEqual(result.agent_voice, "female")
        self.assertEqual(result.messages[-1]["content"], "Theek hai, ab aise baat karti hoon")


class VoiceApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"AUTH_REQUIRED": "false", "AGENT_PROVIDER": "mock"})
        self.env.start()
        app.dependency_overrides.clear()

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id=USER_ID, email="v@example.com", display_name="V")

        app.dependency_overrides[current_user] = signed_in_user
        reset_db()
        self.client = TestClient(app)
        self.conversation_id = self.client.post("/api/agent/conversations").json()["id"]

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.env.stop()

    def test_voice_can_be_set_in_settings(self) -> None:
        response = self.client.patch(
            f"/api/agent/conversations/{self.conversation_id}/settings", json={"agent_voice": "male"}
        )
        self.assertEqual(response.json()["agent_voice"], "male")
        self.assertEqual(get_conversation(self.conversation_id, USER_ID)["agent_voice"], "male")
        bad = self.client.patch(
            f"/api/agent/conversations/{self.conversation_id}/settings", json={"agent_voice": "robot"}
        )
        self.assertEqual(bad.status_code, 422)

    def test_a_voice_asked_for_in_chat_is_saved(self) -> None:
        with patch(
            "agent.runtime.orchestrator.generate_agent_reply",
            AsyncMock(return_value="<voice:male>Chalo, ab aise baat karta hoon"),
        ):
            response = self.client.post(
                f"/api/agent/conversations/{self.conversation_id}/messages",
                json={"message": "ladke ki tarah baat karo"},
            )
        self.assertEqual(response.json()["agent_voice"], "male")
        self.assertEqual(get_conversation(self.conversation_id, USER_ID)["agent_voice"], "male")


if __name__ == "__main__":
    unittest.main()


class IdentityPromptTest(unittest.TestCase):
    def test_live_prompt_says_matches_are_friends(self) -> None:
        reset_db()
        save_conversation({"id": "c", "status": "active", "messages": []}, USER_ID)
        with patch.dict(os.environ, {"AGENT_BEHAVIOR_VERSION": "v3-1"}):
            prompt = _prompt()
        self.assertIn("find friends they would actually get along with", prompt)
        self.assertIn("Matches are friends", prompt)
        self.assertNotIn("dating companion", prompt)
        self.assertNotIn("Dating focus", prompt)
