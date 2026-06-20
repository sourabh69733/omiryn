import os
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from api.main import _agent_user_context, _smart_reply_context_sources, app, current_user
from agent.providers import (
    _compact_chat_reply,
    _context_sources_text,
    _groq_rate_limit_headers,
    _mock_reply,
    _prompt_debug,
    _provider_messages,
    _system_prompt_with_context,
)
from agent.usage import PROFILE_SIGNAL_BACKFILL
from auth import CurrentUser
from ingestion.whatsapp import build_whatsapp_style_summary, parse_whatsapp_export
from storage import (
    _normalize_database_url,
    _reset_db_allowed,
    reset_db,
    save_agent_usage_event,
    upsert_profile_fact,
)


class AgentSubmissionApiTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["AUTH_REQUIRED"] = "false"
        os.environ["AGENT_PROVIDER"] = "mock"
        app.dependency_overrides.clear()
        reset_db()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

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

    def test_reset_db_guard_only_allows_test_databases_by_default(self) -> None:
        self.assertFalse(
            _reset_db_allowed("postgresql+psycopg://omiryn:omiryn@localhost:5432/omiryn")
        )
        self.assertTrue(
            _reset_db_allowed("postgresql+psycopg://omiryn:omiryn@localhost:5432/omiryn_test")
        )
        self.assertTrue(_reset_db_allowed("sqlite:///./data/omiryn_test.db"))
        self.assertFalse(_reset_db_allowed("sqlite:///./data/omiryn.db"))

    def test_user_can_edit_then_approve_draft(self) -> None:
        draft_id = self._create_draft()

        update_response = self.client.patch(
            f"/api/drafts/{draft_id}",
            json={
                "gender": "woman",
                "interested_in": "men",
                "city": "Mumbai",
                "values": ["family", "kindness"],
                "summary": "Updated by user review.",
            },
        )

        self.assertEqual(update_response.status_code, 200)
        updated = update_response.json()
        self.assertEqual(updated["submission"]["gender"]["value"], "woman")
        self.assertEqual(updated["submission"]["interested_in"]["value"], "men")
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

    def test_conversations_are_scoped_to_authenticated_user(self) -> None:
        async def user_a() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        async def user_b() -> CurrentUser:
            return CurrentUser(id="user-b", email="b@example.com")

        app.dependency_overrides[current_user] = user_a
        conversation_response = self.client.post("/api/agent/conversations")
        self.assertEqual(conversation_response.status_code, 201)
        conversation_id = conversation_response.json()["id"]
        self.client.post(
            f"/api/agent/conversations/{conversation_id}/context-sources",
            json={
                "source_type": "manual_notes",
                "title": "Private notes",
                "content": "This context belongs only to user A.",
            },
        )

        app.dependency_overrides[current_user] = user_b
        list_response = self.client.get("/api/agent/conversations")
        get_response = self.client.get(f"/api/agent/conversations/{conversation_id}")
        context_response = self.client.get(
            f"/api/agent/conversations/{conversation_id}/context-sources"
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["conversations"], [])
        self.assertEqual(get_response.status_code, 404)
        self.assertEqual(context_response.status_code, 404)

        app.dependency_overrides[current_user] = user_a
        list_response = self.client.get("/api/agent/conversations")
        self.assertEqual(len(list_response.json()["conversations"]), 1)

    def test_auth_me_returns_current_user(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        response = self.client.get("/api/auth/me")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": "user-a", "email": "a@example.com"})

    def test_dating_basics_are_required_profile_data(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user

        initial_response = self.client.get("/api/me/dating-basics")
        self.assertEqual(initial_response.status_code, 200)
        self.assertFalse(initial_response.json()["complete"])

        save_response = self.client.put(
            "/api/me/dating-basics",
            json={"gender": "man", "interested_in": "women"},
        )
        self.assertEqual(save_response.status_code, 200)
        self.assertTrue(save_response.json()["complete"])

        loaded_response = self.client.get("/api/me/dating-basics")
        self.assertEqual(loaded_response.json()["profile"]["gender"], "man")
        self.assertEqual(loaded_response.json()["profile"]["interested_in"], "women")

    def test_agent_initial_persona_uses_interested_gender(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        self.client.put(
            "/api/me/dating-basics",
            json={"gender": "man", "interested_in": "women"},
        )

        response = self.client.post("/api/agent/conversations")

        self.assertEqual(response.status_code, 201)
        self.assertIn("Annie", response.json()["messages"][0]["content"])

    def test_agent_initial_message_uses_display_name_when_available(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com", display_name="Sourabh")

        app.dependency_overrides[current_user] = signed_in_user
        self.client.put(
            "/api/me/dating-basics",
            json={"gender": "man", "interested_in": "women"},
        )

        response = self.client.post("/api/agent/conversations")

        self.assertEqual(response.status_code, 201)
        self.assertIn("Hey Sourabh, I'm Annie", response.json()["messages"][0]["content"])

    def test_agent_prompt_includes_user_identity_location_and_time_context(self) -> None:
        prompt = _system_prompt_with_context(
            "System",
            context_sources=None,
            user_profile={
                "display_name": "Sourabh",
                "email": "sourabh@example.com",
                "gender": "man",
                "interested_in": "women",
                "location": "India",
                "country": "India",
                "timezone": "Asia/Kolkata",
                "current_date": "2026-06-20",
                "current_time": "10:30",
                "current_weekday": "Saturday",
            },
        )

        self.assertIn("display_name=Sourabh", prompt)
        self.assertIn("email=sourabh@example.com", prompt)
        self.assertIn("location=India", prompt)
        self.assertIn("date=2026-06-20", prompt)
        self.assertIn("timezone=Asia/Kolkata", prompt)

    def test_agent_user_context_uses_detected_city_before_country_default(self) -> None:
        user = CurrentUser(id="user-a", email="a@example.com", display_name="Sourabh")
        upsert_profile_fact(
            {
                "user_id": "user-a",
                "category": "location",
                "key": "city",
                "value": {"city": "Bengaluru"},
                "label": "Is connected to Bengaluru",
                "confidence": 0.7,
            }
        )

        context = _agent_user_context(user)

        self.assertEqual(context["location"], "Bengaluru")
        self.assertEqual(context["country"], "India")

    def test_dating_basics_are_scoped_to_authenticated_user(self) -> None:
        async def user_a() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        async def user_b() -> CurrentUser:
            return CurrentUser(id="user-b", email="b@example.com")

        app.dependency_overrides[current_user] = user_a
        self.client.put(
            "/api/me/dating-basics",
            json={"gender": "woman", "interested_in": "men"},
        )

        app.dependency_overrides[current_user] = user_b
        response = self.client.get("/api/me/dating-basics")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["complete"])

    def test_profile_page_data_includes_account_and_learned_sources(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        save_response = self.client.put(
            "/api/me/profile",
            json={
                "display_name": "Aarav",
                "gender": "man",
                "interested_in": "women",
            },
        )
        self.assertEqual(save_response.status_code, 200)

        conversation_id = self.client.post("/api/agent/conversations").json()["id"]
        self.client.post(
            f"/api/agent/conversations/{conversation_id}/context-sources",
            json={
                "source_type": "manual_notes",
                "title": "Preference memory",
                "content": "The user prefers calm plans and thoughtful conversations.",
            },
        )
        self.client.post(
            f"/api/agent/conversations/{conversation_id}/whatsapp-import",
            json={
                "title": "My text style",
                "user_sender": "Aarav",
                "content": sample_whatsapp_export(),
            },
        )

        profile_response = self.client.get("/api/me/profile")

        self.assertEqual(profile_response.status_code, 200)
        data = profile_response.json()
        self.assertEqual(data["user"], {"id": "user-a", "email": "a@example.com"})
        self.assertEqual(data["profile"]["display_name"], "Aarav")
        self.assertEqual(len(data["memory_sources"]), 1)
        self.assertEqual(len(data["style_sources"]), 1)

    def test_profile_facts_are_grouped_and_scoped_to_user(self) -> None:
        async def user_a() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        async def user_b() -> CurrentUser:
            return CurrentUser(id="user-b", email="b@example.com")

        upsert_profile_fact(
            {
                "user_id": "user-a",
                "category": "communication",
                "key": "conflict_style_preference",
                "value": {"kind": "calm_direct_low_drama"},
                "label": "Prefers calm, low-drama conflict resolution",
                "confidence": 0.72,
                "source_kind": "agent_chat",
                "source_id": "conversation-a",
                "evidence": [{"quote": "I do not enjoy dramatic fights."}],
            }
        )
        upsert_profile_fact(
            {
                "user_id": "user-b",
                "category": "values",
                "key": "family_orientation",
                "value": {"kind": "high"},
                "label": "Values family involvement",
                "confidence": 0.8,
            }
        )

        app.dependency_overrides[current_user] = user_a
        response = self.client.get("/api/me/profile-facts")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["facts"]), 1)
        self.assertEqual(data["facts"][0]["user_id"], "user-a")
        self.assertEqual(data["facts"][0]["category"], "communication")
        self.assertEqual(len(data["groups"]["communication"]), 1)
        self.assertNotIn("values", data["groups"])

    def test_profile_fact_upsert_merges_evidence_and_confidence(self) -> None:
        upsert_profile_fact(
            {
                "user_id": "user-a",
                "category": "values",
                "key": "emotional_maturity",
                "value": {"importance": "medium"},
                "label": "Values emotional maturity",
                "confidence": 0.55,
                "evidence": [{"message_id": "m1"}],
            }
        )
        upsert_profile_fact(
            {
                "user_id": "user-a",
                "category": "values",
                "key": "emotional_maturity",
                "value": {"importance": "high"},
                "label": "Strongly values emotional maturity",
                "confidence": 0.81,
                "evidence": [{"message_id": "m2"}],
            }
        )

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        response = self.client.get("/api/me/profile")

        self.assertEqual(response.status_code, 200)
        facts = response.json()["learned_facts"]
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["label"], "Strongly values emotional maturity")
        self.assertEqual(facts[0]["confidence"], 0.81)
        self.assertEqual(len(facts[0]["evidence"]), 2)

    def test_profile_fact_duplicates_are_deduped_and_evidence_text_is_normalized(self) -> None:
        upsert_profile_fact(
            {
                "user_id": "user-a",
                "category": "behavior",
                "key": "dating_app",
                "value": {"kind": "dating_app"},
                "label": "Using dating app",
                "confidence": 0.85,
                "evidence": [{"text": "I am using dating apps right now."}],
            }
        )
        upsert_profile_fact(
            {
                "user_id": "user-a",
                "category": "behavior",
                "key": "dating_app_use",
                "value": {"kind": "dating_app_use"},
                "label": "Using dating app",
                "confidence": 0.9,
                "evidence": [{"quote": "Dating app use matters here."}],
            }
        )

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        facts = self.client.get("/api/me/profile-facts").json()["facts"]

        self.assertEqual(len(facts), 1)
        self.assertIn(facts[0]["key"], {"dating_app", "dating_app_use"})
        self.assertEqual(facts[0]["confidence"], 0.9)
        self.assertEqual(len(facts[0]["evidence"]), 2)
        evidence_quotes = {item["quote"] for item in facts[0]["evidence"]}
        evidence_texts = {item["text"] for item in facts[0]["evidence"]}
        self.assertIn("I am using dating apps right now.", evidence_quotes)
        self.assertIn("I am using dating apps right now.", evidence_texts)

    def test_raw_profile_data_points_are_env_gated(self) -> None:
        upsert_profile_fact(
            {
                "user_id": "user-a",
                "category": "communication",
                "key": "tone_preference",
                "value": {"kind": "casual"},
                "label": "Prefers casual conversation",
                "confidence": 0.7,
                "evidence": [{"message_id": "m1"}],
            }
        )

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user

        with patch.dict("os.environ", {"PROFILE_DEBUG_DATA_ENABLED": "false"}):
            hidden_response = self.client.get("/api/me/profile")
        self.assertNotIn("raw_internal_data_points", hidden_response.json())

        with patch.dict("os.environ", {"PROFILE_DEBUG_DATA_ENABLED": "true"}):
            visible_response = self.client.get("/api/me/profile")
        raw_points = visible_response.json()["raw_internal_data_points"]
        self.assertEqual(len(raw_points), 1)
        self.assertEqual(raw_points[0]["key"], "tone_preference")
        self.assertEqual(raw_points[0]["evidence_count"], 1)

    def test_draft_profile_includes_user_dating_basics(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        self.client.put(
            "/api/me/dating-basics",
            json={"gender": "man", "interested_in": "women"},
        )

        draft_id = self._create_draft()
        draft = self.client.get(f"/api/drafts/{draft_id}").json()

        self.assertEqual(draft["submission"]["gender"]["value"], "man")
        self.assertEqual(draft["submission"]["gender"]["source"], "user_stated")
        self.assertEqual(draft["submission"]["interested_in"]["value"], "women")
        self.assertEqual(draft["submission"]["interested_in"]["source"], "user_stated")

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

    def test_chat_message_creates_profile_facts_for_authenticated_user(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]

        message_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/messages",
            json={
                "message": (
                    "I want a long-term relationship in Bengaluru. Family and emotional "
                    "maturity matter to me, I prefer calm people, and smoking is a dealbreaker."
                )
            },
        )
        facts_response = self.client.get("/api/me/profile-facts")

        self.assertEqual(message_response.status_code, 200)
        self.assertEqual(facts_response.status_code, 200)
        facts = facts_response.json()["facts"]
        fact_keys = {(fact["category"], fact["key"]) for fact in facts}
        self.assertIn(("dating_intent", "relationship_intent"), fact_keys)
        self.assertIn(("location", "city"), fact_keys)
        self.assertIn(("values", "family"), fact_keys)
        self.assertIn(("communication", "calm_low_drama"), fact_keys)
        self.assertIn(("preferences", "calm_partner"), fact_keys)
        self.assertIn(("dealbreakers", "smoking"), fact_keys)

    def test_deep_profile_fact_extraction_runs_every_fifth_valid_message(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]

        with patch.dict(os.environ, {"AGENT_PROVIDER": "mock"}):
            for index in range(5):
                response = self.client.post(
                    f"/api/agent/conversations/{conversation_id}/messages",
                    json={
                        "message": (
                            f"Career growth, mutual respect, and calm communication matter "
                            f"to me in relationships. Detail {index}."
                        )
                    },
                )
                self.assertEqual(response.status_code, 200)

        usage = self.client.get(f"/api/agent/conversations/{conversation_id}/usage").json()
        request_kinds = [event["request_kind"] for event in usage["events"]]
        self.assertIn("profile_fact_extract", request_kinds)

        facts = self.client.get("/api/me/profile-facts").json()["facts"]
        fact_keys = {(fact["category"], fact["key"]) for fact in facts}
        self.assertIn(("goals", "career_growth"), fact_keys)
        self.assertIn(("values", "mutual_respect"), fact_keys)

    def test_repeated_chat_fact_merges_evidence(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]

        self.client.post(
            f"/api/agent/conversations/{conversation_id}/messages",
            json={"message": "I really value honest and direct communication."},
        )
        self.client.post(
            f"/api/agent/conversations/{conversation_id}/messages",
            json={"message": "Honesty matters a lot to me in relationships."},
        )

        facts = self.client.get("/api/me/profile-facts").json()["facts"]
        honesty_facts = [
            fact for fact in facts if fact["category"] == "values" and fact["key"] == "honesty"
        ]

        self.assertEqual(len(honesty_facts), 1)
        self.assertEqual(len(honesty_facts[0]["evidence"]), 2)

    def test_low_quality_message_does_not_create_profile_facts(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]

        self.client.post(
            f"/api/agent/conversations/{conversation_id}/messages",
            json={"message": "knl"},
        )

        facts_response = self.client.get("/api/me/profile-facts")

        self.assertEqual(facts_response.status_code, 200)
        self.assertEqual(facts_response.json()["facts"], [])

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

    def test_short_no_answers_are_not_marked_low_information(self) -> None:
        conversation_response = self.client.post("/api/agent/conversations")
        conversation_id = conversation_response.json()["id"]

        first_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/messages",
            json={"message": "nhi,"},
        )
        second_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/messages",
            json={"message": "no"},
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertNotEqual(first_response.json()["messages"][-2].get("quality"), "low_information")
        self.assertNotEqual(second_response.json()["messages"][-2].get("quality"), "low_information")

    def test_short_acknowledgements_are_not_marked_low_information(self) -> None:
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]

        for text in ("yep", "ok", "okay"):
            response = self.client.post(
                f"/api/agent/conversations/{conversation_id}/messages",
                json={"message": text},
            )
            self.assertEqual(response.status_code, 200)
            self.assertNotEqual(response.json()["messages"][-2].get("quality"), "low_information")

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

    def test_prompt_debug_counts_system_and_provider_message_chars(self) -> None:
        debug = _prompt_debug(
            "system text",
            [
                {"role": "assistant", "content": "hello"},
                {"role": "user", "content": "world"},
            ],
        )

        self.assertEqual(debug["system_chars"], 11)
        self.assertEqual(debug["message_chars"], 10)
        self.assertEqual(debug["total_chars"], 21)
        self.assertEqual(debug["rough_tokens"], 5)
        self.assertEqual(debug["provider_message_count"], 2)

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

    def test_chat_replies_are_compacted_for_normal_messages(self) -> None:
        reply = _compact_chat_reply(
            (
                "That makes sense, and I can see why this matters to you. "
                "The right person should probably respect your work, your pace, "
                "your family expectations, and your communication style before "
                "anything gets serious. We can slowly figure that out together."
            ),
            [{"role": "user", "content": "yes"}],
        )

        self.assertLessEqual(len(reply.split()), 35)
        self.assertNotIn("slowly figure", reply)

    def test_mock_companion_reply_stays_short(self) -> None:
        reply = _mock_reply(
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "Hey, I'm Annie."},
                {"role": "user", "content": "career matters to me"},
            ],
            {"interested_in": "women"},
        )

        self.assertLessEqual(len(reply.split()), 6)

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

    def test_main_usage_dashboard_is_app_wide(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-b", email="b@example.com")

        save_agent_usage_event(
            {
                "user_id": "user-a",
                "conversation_id": None,
                "request_kind": "chat_reply",
                "provider": "groq",
                "model": "llama-3.3-70b-versatile",
                "success": True,
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "latency_ms": 50,
                "raw_usage": {},
            }
        )
        save_agent_usage_event(
            {
                "user_id": "user-a",
                "conversation_id": None,
                "request_kind": PROFILE_SIGNAL_BACKFILL,
                "provider": "groq",
                "model": "llama-3.1-8b-instant",
                "success": True,
                "prompt_tokens": 400,
                "completion_tokens": 80,
                "total_tokens": 480,
                "latency_ms": 120,
                "raw_usage": {},
            }
        )
        app.dependency_overrides[current_user] = signed_in_user

        response = self.client.get("/api/agent/usage")

        self.assertEqual(response.status_code, 200)
        summary = response.json()["summary"]
        events = response.json()["events"]
        self.assertEqual(summary["request_count"], 2)
        self.assertEqual(summary["total_tokens"], 600)
        self.assertEqual(summary["chat_message_count"], 1)
        self.assertEqual(summary["average_tokens_per_message"], 120)
        self.assertEqual(summary["average_prompt_tokens_per_message"], 100)
        self.assertEqual(summary["average_completion_tokens_per_message"], 20)
        self.assertIn(PROFILE_SIGNAL_BACKFILL, {event["request_kind"] for event in events})

    def test_admin_overview_aggregates_users_activity_and_usage(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        self.client.put(
            "/api/me/profile",
            json={
                "display_name": "Aarav",
                "gender": "man",
                "interested_in": "women",
            },
        )
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]
        self.client.post(
            f"/api/agent/conversations/{conversation_id}/context-sources",
            json={
                "source_type": "manual_notes",
                "title": "Admin visible note",
                "content": "The user prefers kind communication and calm plans.",
            },
        )
        self.client.post("/api/agent-submissions/profile", json=sample_submission())
        upsert_profile_fact(
            {
                "user_id": "user-a",
                "category": "values",
                "key": "kindness",
                "value": {"kind": "kindness"},
                "label": "Values kindness",
                "confidence": 0.8,
            }
        )
        save_agent_usage_event(
            {
                "user_id": "user-a",
                "conversation_id": conversation_id,
                "request_kind": "chat_reply",
                "provider": "groq",
                "model": "llama-3.3-70b-versatile",
                "success": True,
                "prompt_tokens": 90,
                "completion_tokens": 30,
                "total_tokens": 120,
                "latency_ms": 80,
                "estimated_cost_usd": 0.0001,
                "raw_usage": {},
            }
        )
        app.dependency_overrides.clear()

        response = self.client.get("/api/admin/overview")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["summary"]["user_count"], 1)
        self.assertEqual(data["summary"]["conversation_count"], 1)
        self.assertEqual(data["summary"]["draft_count"], 1)
        self.assertEqual(data["summary"]["learned_fact_count"], 1)
        self.assertEqual(data["summary"]["context_source_count"], 1)
        self.assertEqual(data["summary"]["active_user_7d_count"], 1)
        self.assertEqual(data["summary"]["onboarding_started_user_count"], 1)
        self.assertEqual(data["summary"]["onboarding_completed_user_count"], 1)
        self.assertEqual(data["summary"]["approved_profile_user_count"], 0)
        self.assertEqual(data["summary"]["missing_profile_basics_user_count"], 0)
        self.assertEqual(data["summary"]["new_user_7d_count"], 1)
        self.assertEqual(data["summary"]["open_draft_count"], 1)
        self.assertEqual(data["summary"]["agent_failure_today_count"], 0)
        self.assertEqual(data["summary"]["usage"]["request_count"], 1)
        self.assertEqual(data["summary"]["usage"]["total_tokens"], 120)
        self.assertEqual(data["users"][0]["user_id"], "user-a")
        self.assertEqual(data["users"][0]["display_name"], "Aarav")
        self.assertEqual(data["users"][0]["usage"]["total_tokens"], 120)
        self.assertEqual(data["recent_conversations"][0]["id"], conversation_id)
        self.assertEqual(data["recent_usage_events"][0]["provider"], "groq")

    def test_admin_usage_dashboard_response_matches_usage_contract(self) -> None:
        save_agent_usage_event(
            {
                "user_id": "user-a",
                "conversation_id": None,
                "request_kind": "chat_reply",
                "provider": "groq",
                "model": "llama-3.3-70b-versatile",
                "success": True,
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "latency_ms": 50,
                "raw_usage": {},
            }
        )
        with patch.dict(
            "os.environ",
            {
                "GROQ_RPD_LIMIT": "1000",
                "GROQ_TPD_LIMIT": "100000",
                "GROQ_RPM_LIMIT": "30",
                "GROQ_TPM_LIMIT": "6000",
            },
        ):
            response = self.client.get("/api/admin/usage")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["summary"]["request_count"], 1)
        self.assertEqual(data["summary"]["total_tokens"], 120)
        self.assertEqual(data["events"][0]["provider"], "groq")
        self.assertEqual(data["limits"]["groq_rpd"], 1000)
        self.assertEqual(data["limits"]["groq_tpd"], 100000)
        self.assertEqual(data["limits"]["groq_rpm"], 30)
        self.assertEqual(data["limits"]["groq_tpm"], 6000)

    def test_admin_user_detail_filters_user_report_data(self) -> None:
        async def user_a() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        async def user_b() -> CurrentUser:
            return CurrentUser(id="user-b", email="b@example.com")

        app.dependency_overrides[current_user] = user_a
        conversation_a = self.client.post("/api/agent/conversations").json()["id"]
        draft_a = self.client.post("/api/agent-submissions/profile", json=sample_submission()).json()
        upsert_profile_fact(
            {
                "user_id": "user-a",
                "category": "values",
                "key": "kindness",
                "value": {"kind": "kindness"},
                "label": "Values kindness",
                "confidence": 0.8,
            }
        )
        save_agent_usage_event(
            {
                "user_id": "user-a",
                "conversation_id": conversation_a,
                "request_kind": "chat_reply",
                "provider": "groq",
                "model": "llama-3.3-70b-versatile",
                "success": True,
                "prompt_tokens": 40,
                "completion_tokens": 10,
                "total_tokens": 50,
                "latency_ms": 40,
                "raw_usage": {},
            }
        )

        app.dependency_overrides[current_user] = user_b
        conversation_b = self.client.post("/api/agent/conversations").json()["id"]
        save_agent_usage_event(
            {
                "user_id": "user-b",
                "conversation_id": conversation_b,
                "request_kind": "chat_reply",
                "provider": "mock",
                "model": "mock",
                "success": True,
                "total_tokens": 0,
                "latency_ms": 0,
                "raw_usage": {},
            }
        )
        app.dependency_overrides.clear()

        response = self.client.get("/api/admin/users/user-a")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["user"]["user_id"], "user-a")
        self.assertEqual(data["user"]["display_name"], "Aarav")
        self.assertEqual(data["user"]["display_name_source"], "draft")
        self.assertEqual(data["profile"]["display_name"], "Aarav")
        self.assertEqual(data["profile"]["source"], "draft")
        self.assertEqual([conversation["id"] for conversation in data["conversations"]], [conversation_a])
        self.assertEqual([draft["id"] for draft in data["drafts"]], [draft_a["draft_id"]])
        self.assertEqual([fact["label"] for fact in data["facts"]], ["Values kindness"])
        self.assertEqual(data["usage_events"][0]["user_id"], "user-a")
        self.assertEqual(data["usage_events"][0]["total_tokens"], 50)

    def test_admin_pages_serve_separate_admin_shell(self) -> None:
        response = self.client.get("/admin")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Omiryn Admin", response.text)
        self.assertIn("/admin/static/app.js", response.text)

    def test_admin_api_rejects_non_admin_when_admins_are_configured(self) -> None:
        async def non_admin_user() -> CurrentUser:
            return CurrentUser(id="user-b", email="b@example.com")

        app.dependency_overrides[current_user] = non_admin_user
        with patch.dict(
            "os.environ",
            {
                "AUTH_REQUIRED": "true",
                "ADMIN_EMAILS": "admin@example.com",
                "ADMIN_USER_IDS": "",
            },
        ):
            response = self.client.get("/api/admin/overview")

        self.assertEqual(response.status_code, 403)

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
                "PROFILE_DEBUG_DATA_ENABLED": "true",
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
                "profile_debug_data_enabled": True,
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
        self.assertEqual(len(list_response.json()["available_sources"]), 1)
        self.assertTrue(list_response.json()["available_sources"][0]["attached"])

    def test_user_context_can_attach_to_another_session(self) -> None:
        first_response = self.client.post("/api/agent/conversations")
        first_conversation_id = first_response.json()["id"]
        create_response = self.client.post(
            f"/api/agent/conversations/{first_conversation_id}/context-sources",
            json={
                "source_type": "llm_profile",
                "title": "Reusable profile",
                "content": "The user cares about career growth and calm communication.",
            },
        )
        source_id = create_response.json()["id"]
        second_response = self.client.post("/api/agent/conversations")
        second_conversation_id = second_response.json()["id"]

        list_response = self.client.get(
            f"/api/agent/conversations/{second_conversation_id}/context-sources"
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["count"], 0)
        self.assertFalse(list_response.json()["available_sources"][0]["attached"])

        attach_response = self.client.put(
            f"/api/agent/conversations/{second_conversation_id}/context-sources/attachments",
            json={"source_ids": [source_id]},
        )
        self.assertEqual(attach_response.status_code, 200)
        self.assertEqual(attach_response.json()["count"], 1)
        self.assertTrue(attach_response.json()["available_sources"][0]["attached"])

        sources = _smart_reply_context_sources(
            second_conversation_id,
            None,
            "what do you know about my career?",
        )
        self.assertEqual(sources[0]["title"], "Reusable profile")

        detach_response = self.client.put(
            f"/api/agent/conversations/{second_conversation_id}/context-sources/attachments",
            json={"source_ids": []},
        )
        self.assertEqual(detach_response.status_code, 200)
        self.assertEqual(detach_response.json()["count"], 0)
        self.assertFalse(detach_response.json()["available_sources"][0]["attached"])

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

    def test_friend_style_import_can_infer_sender_when_blank(self) -> None:
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

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["source_type"], "friend_style")
        self.assertEqual(data["metadata"]["selected_sender"], "Aarav")
        self.assertTrue(data["metadata"]["selected_sender_inferred"])

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
