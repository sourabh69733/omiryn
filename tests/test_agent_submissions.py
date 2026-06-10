import unittest

from fastapi.testclient import TestClient

from api.main import app
from storage import reset_db


class AgentSubmissionApiTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        self.client = TestClient(app)

    def test_agent_submission_creates_reviewable_draft(self) -> None:
        response = self.client.post("/api/agent-submissions/profile", json=sample_submission())

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["status"], "draft")
        self.assertTrue(data["review_url"].startswith("/drafts/"))

        draft_response = self.client.get(f"/api/drafts/{data['draft_id']}")
        self.assertEqual(draft_response.status_code, 200)
        self.assertEqual(draft_response.json()["submission"]["display_name"], "Aarav")

    def test_user_can_edit_then_approve_draft(self) -> None:
        draft_id = self._create_draft()

        update_response = self.client.patch(
            f"/api/drafts/{draft_id}",
            json={
                "city": "Mumbai",
                "values": ["family", "kindness"],
                "summary": "Updated by user review.",
            },
        )

        self.assertEqual(update_response.status_code, 200)
        updated = update_response.json()
        self.assertEqual(updated["submission"]["city"]["value"], "Mumbai")
        self.assertEqual(updated["submission"]["city"]["source"], "user_stated")

        approve_response = self.client.post(f"/api/drafts/{draft_id}/approve")
        self.assertEqual(approve_response.status_code, 200)
        self.assertEqual(approve_response.json()["status"], "approved")

    def test_deleted_draft_is_not_readable(self) -> None:
        draft_id = self._create_draft()

        delete_response = self.client.delete(f"/api/drafts/{draft_id}")

        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(self.client.get(f"/api/drafts/{draft_id}").status_code, 404)

    def test_omiryn_agent_conversation_extracts_to_review_draft(self) -> None:
        conversation_response = self.client.post("/api/agent/conversations")
        self.assertEqual(conversation_response.status_code, 201)
        conversation_id = conversation_response.json()["id"]

        message_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/messages",
            json={
                "message": (
                    "I want a long-term relationship in Bengaluru. Family and emotional "
                    "stability matter, and smoking is a dealbreaker."
                )
            },
        )
        self.assertEqual(message_response.status_code, 200)
        self.assertGreaterEqual(len(message_response.json()["messages"]), 3)

        extract_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/extract"
        )
        self.assertEqual(extract_response.status_code, 200)
        draft_id = extract_response.json()["draft_id"]
        draft_response = self.client.get(f"/api/drafts/{draft_id}")
        self.assertEqual(draft_response.status_code, 200)
        self.assertEqual(
            draft_response.json()["submission"]["relationship_intent"]["value"],
            "long_term",
        )

    def test_agent_status_exposes_safe_runtime_config(self) -> None:
        response = self.client.get("/api/agent/status")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("provider", data)
        self.assertIn("model", data)
        self.assertIn("groq_api_key_loaded", data)
        self.assertNotIn("groq_api_key", data)

    def _create_draft(self) -> str:
        response = self.client.post("/api/agent-submissions/profile", json=sample_submission())
        return response.json()["draft_id"]


def sample_submission() -> dict[str, object]:
    return {
        "agent_provider": "chatgpt",
        "display_name": "Aarav",
        "age": 29,
        "city": {"value": "Bengaluru", "source": "user_stated", "confidence": 0.95},
        "relationship_intent": {
            "value": "long_term",
            "source": "user_stated",
            "confidence": 0.92,
        },
        "values": {
            "values": ["family", "ambition"],
            "source": "user_stated",
            "confidence": 0.86,
        },
        "lifestyle": {
            "values": ["fitness", "travel"],
            "source": "inferred",
            "confidence": 0.72,
        },
        "communication_style": {
            "value": "direct",
            "source": "user_stated",
            "confidence": 0.82,
        },
        "family_expectations": {
            "value": "medium involvement",
            "source": "user_stated",
            "confidence": 0.8,
        },
        "children_preference": {
            "value": "wants_children",
            "source": "inferred",
            "confidence": 0.62,
        },
        "dealbreakers": {
            "values": ["smoking"],
            "source": "user_stated",
            "confidence": 0.91,
        },
        "soft_preferences": {
            "values": ["Bengaluru", "emotionally steady"],
            "source": "inferred",
            "confidence": 0.7,
        },
        "summary": "Looking for a serious relationship.",
    }


if __name__ == "__main__":
    unittest.main()
