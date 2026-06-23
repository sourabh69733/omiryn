import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.data_points import normalize_data_point, rank_data_points_for_context
from agent.prompt_builder import build_companion_system_prompt
from api.main import app
from storage import reset_db


class AgentControlFrameworkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(
            "os.environ",
            {"AGENT_PROVIDER": "mock", "AUTH_REQUIRED": "false"},
        )
        self.env_patch.start()
        reset_db()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.env_patch.stop()

    def test_prompt_builder_keeps_behavior_and_context_explicit(self) -> None:
        prompt = build_companion_system_prompt(
            user_profile={"interested_in": "women", "display_name": "Aarav"},
            agent_name="Annie",
            agent_tone="warm",
            context_sources=[
                {
                    "source_type": "llm_profile",
                    "title": "Imported profile",
                    "content": "The user values calm communication.",
                }
            ],
        )

        self.assertIn("Behavior version: companion-v1", prompt)
        self.assertIn("Agent persona: name=Annie", prompt)
        self.assertIn("Tone setting: Warm", prompt)
        self.assertIn("[llm_profile] Imported profile", prompt)

    def test_data_points_default_to_matching_not_chat_context(self) -> None:
        point = normalize_data_point(
            {
                "user_id": "user-a",
                "category": "Values",
                "key": "Mutual Respect",
                "label": "Values mutual respect",
                "value": {"kind": "mutual_respect"},
                "confidence": 0.8,
            }
        )

        self.assertTrue(point["used_for_matching"])
        self.assertFalse(point["used_for_chat_context"])
        self.assertEqual(point["category"], "values")
        self.assertEqual(point["key"], "mutual_respect")

    def test_data_point_context_ranking_uses_only_chat_enabled_points(self) -> None:
        ranked = rank_data_points_for_context(
            [
                {
                    "status": "active",
                    "used_for_chat_context": True,
                    "category": "values",
                    "key": "calm_communication",
                    "label": "Values calm communication",
                    "value": {"kind": "calm_communication"},
                    "confidence": 0.7,
                },
                {
                    "status": "active",
                    "used_for_chat_context": False,
                    "category": "location",
                    "key": "bengaluru",
                    "label": "Lives in Bengaluru",
                    "value": {"city": "Bengaluru"},
                    "confidence": 0.9,
                },
            ],
            "what do you know about my communication?",
        )

        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["key"], "calm_communication")

    def test_feedback_api_stores_agent_message_feedback(self) -> None:
        conversation = self.client.post("/api/agent/conversations").json()
        conversation_id = conversation["id"]

        response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/messages/0/feedback",
            json={"rating": "bad", "reason": "bad_tone", "comment": "Too formal."},
        )
        list_response = self.client.get(f"/api/agent/conversations/{conversation_id}/feedback")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["feedback"]["rating"], "bad")
        self.assertEqual(response.json()["feedback"]["reason"], "bad_tone")
        self.assertEqual(list_response.json()["count"], 1)

    def test_feedback_api_rejects_user_message_feedback(self) -> None:
        conversation = self.client.post("/api/agent/conversations").json()
        conversation_id = conversation["id"]
        self.client.post(
            f"/api/agent/conversations/{conversation_id}/messages",
            json={"message": "I value calm communication."},
        )

        response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/messages/1/feedback",
            json={"rating": "good"},
        )

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
