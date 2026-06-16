import os
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from api.main import _smart_reply_context_sources, app
from agent.providers import _context_sources_text, _groq_rate_limit_headers, _provider_messages
from ingestion.whatsapp import build_whatsapp_style_summary, parse_whatsapp_export
from storage import _normalize_database_url, reset_db


class AgentSubmissionApiTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["AUTH_REQUIRED"] = "false"
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

    def test_database_url_normalizes_postgres_driver(self) -> None:
        self.assertEqual(
            _normalize_database_url("postgres://user:pass@localhost:5432/omiryn"),
            "postgresql+psycopg://user:pass@localhost:5432/omiryn",
        )
        self.assertEqual(
            _normalize_database_url("postgresql://user:pass@localhost:5432/omiryn"),
            "postgresql+psycopg://user:pass@localhost:5432/omiryn",
        )
        self.assertEqual(
            _normalize_database_url("postgresql+psycopg://user:pass@localhost:5432/omiryn"),
            "postgresql+psycopg://user:pass@localhost:5432/omiryn",
        )

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

    def test_conversation_can_be_deleted_with_context(self) -> None:
        conversation_response = self.client.post("/api/agent/conversations")
        self.assertEqual(conversation_response.status_code, 201)
        conversation_id = conversation_response.json()["id"]

        context_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/context-sources",
            json={
                "source_type": "manual_notes",
                "title": "Preference notes",
                "content": "A calm lifestyle and thoughtful communication matter a lot.",
            },
        )
        self.assertEqual(context_response.status_code, 201)

        delete_response = self.client.delete(f"/api/agent/conversations/{conversation_id}")

        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.json()["status"], "deleted")
        self.assertEqual(
            self.client.get(f"/api/agent/conversations/{conversation_id}").status_code,
            404,
        )
        conversations = self.client.get("/api/agent/conversations").json()["conversations"]
        self.assertEqual(conversations, [])

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

    def test_yes_is_allowed_after_confirmation_question(self) -> None:
        conversation_response = self.client.post("/api/agent/conversations")
        conversation = conversation_response.json()
        conversation_id = conversation["id"]
        conversation["messages"] = [
            {
                "role": "assistant",
                "content": (
                    "koi bhi city thik hai, tu flexible hai, aur priority career aur "
                    "relationship ki mutual respect hai, sahi samajh raha hu?"
                ),
            }
        ]
        from storage import save_conversation

        save_conversation(conversation)

        message_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/messages",
            json={"message": "yes"},
        )

        self.assertEqual(message_response.status_code, 200)
        messages = message_response.json()["messages"]
        self.assertNotEqual(messages[-2].get("quality"), "low_information")

    def test_provider_messages_strip_internal_metadata(self) -> None:
        messages = _provider_messages(
            [
                {"role": "assistant", "content": "Question"},
                {"role": "user", "content": "knl", "quality": "low_information"},
                {"role": "user", "content": "I want something serious."},
            ]
        )

        self.assertEqual(
            messages,
            [
                {"role": "assistant", "content": "Question"},
                {"role": "user", "content": "knl"},
                {"role": "user", "content": "I want something serious."},
            ],
        )

    def test_provider_messages_compact_old_history(self) -> None:
        messages = [
            {"role": "user" if index % 2 else "assistant", "content": f"message {index}"}
            for index in range(18)
        ]

        compacted = _provider_messages(messages)

        self.assertEqual(len(compacted), 13)
        self.assertEqual(compacted[0]["role"], "system")
        self.assertIn("Earlier conversation summary", compacted[0]["content"])
        self.assertEqual(compacted[-1]["content"], "message 17")

    def test_context_sources_are_capped_before_provider_call(self) -> None:
        context_text = _context_sources_text(
            [
                {
                    "source_type": "friend_style",
                    "title": "Sanjay-style",
                    "content": "style " * 1000,
                },
                {
                    "source_type": "llm_profile",
                    "title": "Profile",
                    "content": "profile " * 1000,
                },
            ]
        )

        self.assertIn("[friend_style] Sanjay-style", context_text)
        self.assertIn("[llm_profile] Profile", context_text)
        self.assertLess(len(context_text), 3800)

    def test_groq_rate_limit_headers_are_captured(self) -> None:
        response = httpx.Response(
            429,
            headers={
                "retry-after": "2",
                "x-ratelimit-limit-requests": "14400",
                "x-ratelimit-remaining-requests": "14399",
                "x-ratelimit-limit-tokens": "18000",
                "x-ratelimit-remaining-tokens": "12000",
                "x-ratelimit-reset-requests": "2m",
                "x-ratelimit-reset-tokens": "7s",
                "ignored-header": "nope",
            },
        )

        headers = _groq_rate_limit_headers(response)

        self.assertEqual(headers["retry-after"], "2")
        self.assertEqual(headers["x-ratelimit-limit-requests"], "14400")
        self.assertEqual(headers["x-ratelimit-remaining-tokens"], "12000")
        self.assertNotIn("ignored-header", headers)

    def test_usage_response_includes_configured_limits(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "GROQ_RPD_LIMIT": "1000",
                "GROQ_TPD_LIMIT": "100000",
                "GROQ_RPM_LIMIT": "30",
                "GROQ_TPM_LIMIT": "6000",
            },
        ):
            response = self.client.get("/api/agent/usage")

        self.assertEqual(response.status_code, 200)
        limits = response.json()["limits"]
        self.assertEqual(limits["groq_rpd"], 1000)
        self.assertEqual(limits["groq_tpd"], 100000)
        self.assertEqual(limits["groq_rpm"], 30)
        self.assertEqual(limits["groq_tpm"], 6000)

    def test_agent_status_exposes_safe_runtime_config(self) -> None:
        response = self.client.get("/api/agent/status")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("provider", data)
        self.assertIn("model", data)
        self.assertIn("available_models", data)
        self.assertIn("groq_api_key_loaded", data)
        self.assertNotIn("groq_api_key", data)

    def test_auth_config_exposes_public_supabase_settings(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_ANON_KEY": "anon-public-key",
                "AUTH_REQUIRED": "true",
            },
        ):
            response = self.client.get("/api/auth/config")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "supabase_url": "https://example.supabase.co",
                "supabase_anon_key": "anon-public-key",
                "auth_required": True,
            },
        )

    def test_auth_required_blocks_anonymous_user_data_routes(self) -> None:
        with patch.dict("os.environ", {"AUTH_REQUIRED": "true"}):
            response = self.client.get("/api/agent/conversations")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Sign in to continue.")

    def test_conversation_can_store_selected_model(self) -> None:
        response = self.client.post(
            "/api/agent/conversations",
            json={"agent_model": "mock", "agent_mode": "coach_me", "agent_tone": "casual"},
        )

        self.assertEqual(response.status_code, 201)
        conversation = response.json()
        self.assertEqual(conversation["agent_model"], "mock")
        self.assertEqual(conversation["agent_mode"], "coach_me")
        self.assertEqual(conversation["agent_tone"], "casual")

        update_response = self.client.patch(
            f"/api/agent/conversations/{conversation['id']}/settings",
            json={"agent_model": "mock", "agent_mode": "talk_like_me", "agent_tone": "direct"},
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["agent_model"], "mock")
        self.assertEqual(update_response.json()["agent_mode"], "talk_like_me")
        self.assertEqual(update_response.json()["agent_tone"], "direct")

        tone_response = self.client.get(f"/api/agent/conversations/{conversation['id']}/tone")
        self.assertEqual(tone_response.status_code, 200)
        self.assertEqual(tone_response.json()["selected_tone"], "direct")
        self.assertIn("detected_tone", tone_response.json())

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

    def test_reply_context_ignores_imports_until_memory_is_requested(self) -> None:
        conversation_response = self.client.post("/api/agent/conversations")
        conversation_id = conversation_response.json()["id"]
        self.client.post(
            f"/api/agent/conversations/{conversation_id}/context-sources",
            json={
                "source_type": "llm_profile",
                "title": "Career profile",
                "content": "The user is focused on career growth and calm communication.",
            },
        )

        sources = _smart_reply_context_sources(conversation_id, None, "haan, sounds good")

        self.assertEqual(sources, [])

    def test_reply_context_retrieves_relevant_imported_memory(self) -> None:
        conversation_response = self.client.post("/api/agent/conversations")
        conversation_id = conversation_response.json()["id"]
        self.client.post(
            f"/api/agent/conversations/{conversation_id}/context-sources",
            json={
                "source_type": "llm_profile",
                "title": "Career profile",
                "content": "The user is focused on career growth and calm communication.",
            },
        )
        self.client.post(
            f"/api/agent/conversations/{conversation_id}/context-sources",
            json={
                "source_type": "manual_notes",
                "title": "Food notes",
                "content": "The user likes spicy street food.",
            },
        )

        sources = _smart_reply_context_sources(
            conversation_id,
            None,
            "what do you know about my career from imported memory?",
        )

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["title"], "Career profile")

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

    def test_friend_style_import_can_be_selected_for_replies(self) -> None:
        conversation_response = self.client.post("/api/agent/conversations")
        conversation_id = conversation_response.json()["id"]

        create_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/whatsapp-import",
            json={
                "title": "Sanjay-style",
                "user_sender": "Aarav",
                "style_name": "Sanjay-style",
                "style_kind": "friend_style",
                "content": sample_whatsapp_export(),
            },
        )

        self.assertEqual(create_response.status_code, 201)
        style_source = create_response.json()
        self.assertEqual(style_source["source_type"], "friend_style")
        self.assertIn("Friend-style text profile", style_source["preview"])

        update_response = self.client.patch(
            f"/api/agent/conversations/{conversation_id}/settings",
            json={"agent_style_source_id": style_source["id"]},
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["agent_style_source_id"], style_source["id"])

        clear_response = self.client.patch(
            f"/api/agent/conversations/{conversation_id}/settings",
            json={"agent_style_source_id": None},
        )
        self.assertEqual(clear_response.status_code, 200)
        self.assertIsNone(clear_response.json()["agent_style_source_id"])

    def test_friend_style_import_requires_sender_to_learn(self) -> None:
        conversation_response = self.client.post("/api/agent/conversations")
        conversation_id = conversation_response.json()["id"]

        response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/whatsapp-import",
            json={
                "title": "Sanjay-style",
                "style_name": "Sanjay-style",
                "style_kind": "friend_style",
                "content": sample_whatsapp_export(),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("exact WhatsApp sender", response.json()["detail"])

    def test_whatsapp_parser_supports_multiline_exports(self) -> None:
        messages = parse_whatsapp_export(sample_whatsapp_export())

        self.assertEqual(len(messages), 6)
        self.assertEqual(messages[0].sender, "Aarav")
        self.assertIn("second line", messages[2].content)

        summary = build_whatsapp_style_summary(sample_whatsapp_export(), "Aarav")
        self.assertEqual(summary.metadata["selected_sender"], "Aarav")
        self.assertFalse(summary.metadata["raw_chat_stored"])
        self.assertIn("User messages analyzed: 3", summary.content)
        self.assertIn("Recent chat context", summary.content)
        self.assertIn("Last parsed sender: Riya", summary.content)
        self.assertIn("Recent topic terms:", summary.content)

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
