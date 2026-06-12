import unittest

from fastapi.testclient import TestClient

from api.main import app
from ingestion.whatsapp import build_whatsapp_style_summary, parse_whatsapp_export
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

        usage_response = self.client.get(f"/api/agent/conversations/{conversation_id}/usage")
        self.assertEqual(usage_response.status_code, 200)
        usage = usage_response.json()
        self.assertEqual(usage["summary"]["request_count"], 2)
        self.assertEqual(usage["summary"]["successful_request_count"], 2)
        self.assertEqual(
            {event["request_kind"] for event in usage["events"]},
            {"chat_reply", "profile_extract"},
        )

    def test_low_quality_agent_answer_is_rejected_before_model_call(self) -> None:
        conversation_response = self.client.post("/api/agent/conversations")
        conversation_id = conversation_response.json()["id"]

        message_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/messages",
            json={"message": "knl"},
        )

        self.assertEqual(message_response.status_code, 200)
        messages = message_response.json()["messages"]
        self.assertEqual(messages[-2]["quality"], "low_information")
        self.assertIn("real answer", messages[-1]["content"])

        usage_response = self.client.get(f"/api/agent/conversations/{conversation_id}/usage")
        usage = usage_response.json()
        self.assertEqual(usage["summary"]["request_count"], 1)
        self.assertEqual(usage["events"][0]["request_kind"], "input_guardrail")
        self.assertEqual(usage["events"][0]["provider"], "guardrail")

    def test_agent_status_exposes_safe_runtime_config(self) -> None:
        response = self.client.get("/api/agent/status")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("provider", data)
        self.assertIn("model", data)
        self.assertIn("available_models", data)
        self.assertIn("groq_api_key_loaded", data)
        self.assertNotIn("groq_api_key", data)

    def test_conversation_can_store_selected_model(self) -> None:
        response = self.client.post(
            "/api/agent/conversations",
            json={"agent_model": "mock"},
        )

        self.assertEqual(response.status_code, 201)
        conversation = response.json()
        self.assertEqual(conversation["agent_model"], "mock")

        update_response = self.client.patch(
            f"/api/agent/conversations/{conversation['id']}/settings",
            json={"agent_model": "mock"},
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["agent_model"], "mock")

    def test_conversation_can_import_external_context(self) -> None:
        conversation_response = self.client.post("/api/agent/conversations")
        conversation_id = conversation_response.json()["id"]

        prompt_response = self.client.get("/api/context-import-prompt")
        self.assertEqual(prompt_response.status_code, 200)
        self.assertIn("privacy-safe self-profile", prompt_response.json()["prompt"])

        create_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/context-sources",
            json={
                "source_type": "llm_profile",
                "title": "ChatGPT summary",
                "content": (
                    "The user values calm communication, long-term commitment, "
                    "family compatibility, and emotionally steady partners."
                ),
            },
        )

        self.assertEqual(create_response.status_code, 201)
        created = create_response.json()
        self.assertEqual(created["title"], "ChatGPT summary")
        self.assertGreater(created["content_length"], 20)
        self.assertNotIn("content", created)

        list_response = self.client.get(
            f"/api/agent/conversations/{conversation_id}/context-sources"
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["count"], 1)

    def test_whatsapp_export_import_creates_style_context(self) -> None:
        conversation_response = self.client.post("/api/agent/conversations")
        conversation_id = conversation_response.json()["id"]

        create_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/whatsapp-import",
            json={
                "title": "Friend chat style",
                "user_sender": "Aarav",
                "content": sample_whatsapp_export(),
            },
        )

        self.assertEqual(create_response.status_code, 201)
        created = create_response.json()
        self.assertEqual(created["source_type"], "whatsapp_chat")
        self.assertEqual(created["title"], "Friend chat style")
        self.assertIn("WhatsApp speaking-style context", created["preview"])
        self.assertNotIn("Riya:", created["preview"])

        list_response = self.client.get(
            f"/api/agent/conversations/{conversation_id}/context-sources"
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["count"], 1)

    def test_whatsapp_parser_supports_multiline_exports(self) -> None:
        messages = parse_whatsapp_export(sample_whatsapp_export())

        self.assertEqual(len(messages), 6)
        self.assertEqual(messages[0].sender, "Aarav")
        self.assertIn("second line", messages[2].content)

        summary = build_whatsapp_style_summary(sample_whatsapp_export(), "Aarav")
        self.assertEqual(summary.metadata["selected_sender"], "Aarav")
        self.assertFalse(summary.metadata["raw_chat_stored"])
        self.assertIn("User messages analyzed: 3", summary.content)

    def test_usage_page_is_served(self) -> None:
        response = self.client.get("/usage")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Token and cost control", response.text)

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


def sample_whatsapp_export() -> str:
    return """12/06/2026, 10:00 AM - Aarav: hey I am running late but I will call you
12/06/2026, 10:01 AM - Riya: no problem
12/06/2026, 10:02 AM - Aarav: also I was thinking about that plan
second line of same message
12/06/2026, 10:03 AM - Riya: what plan?
12/06/2026, 10:04 AM - Aarav: coffee first, then walk?
12/06/2026, 10:05 AM - Riya: okay"""


if __name__ == "__main__":
    unittest.main()
