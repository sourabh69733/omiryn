import os
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from api.main import STATIC_DIR, _agent_user_context, _smart_reply_context_sources, app, current_user
from agent.runtime.providers import (
    _compact_chat_reply,
    _context_sources_text,
    _estimated_cost_usd,
    _groq_rate_limit_headers,
    _mock_reply,
    _openai_compatible_provider_config,
    _prompt_debug,
    _provider_token_costs,
    _provider_messages,
    _system_prompt_with_context,
    agent_runtime_status,
)
from agent.runtime.usage import PROFILE_SIGNAL_BACKFILL
from auth import CurrentUser
from ingestion.whatsapp import (
    build_whatsapp_structured_memory,
    build_whatsapp_style_summary,
    parse_whatsapp_export,
    prepare_whatsapp_export_text,
)
from storage import (
    _normalize_database_url,
    _reset_db_allowed,
    get_profile_fact,
    list_data_point_extraction_debug,
    list_data_point_feedback,
    list_agent_context_snapshots,
    list_agent_trace_steps,
    list_agent_traces,
    list_context_sources,
    list_profile_facts,
    list_whatsapp_chunks,
    list_whatsapp_imports,
    list_whatsapp_messages,
    list_whatsapp_people,
    list_whatsapp_style_profiles,
    reset_db,
    save_data_point_extraction_debug,
    save_data_point_feedback,
    save_agent_message_feedback,
    save_agent_usage_event,
    upsert_profile_fact,
)


class AgentSubmissionApiTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["AUTH_REQUIRED"] = "false"
        os.environ["AGENT_PROVIDER"] = "mock"
        os.environ["DATA_POINT_EXTRACTOR"] = "rules"
        self.photo_storage_patch = patch("api.main.PROFILE_PHOTO_GCS_BUCKET", "")
        self.photo_storage_patch.start()
        app.dependency_overrides.clear()
        reset_db()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.photo_storage_patch.stop()
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

    def test_conversation_delete_keeps_context_memory(self) -> None:
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
        remaining_context = list_context_sources(conversation_id, None)
        self.assertEqual(len(remaining_context), 1)
        self.assertEqual(remaining_context[0]["title"], "Preference notes")

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
            json={
                "display_name": "Aarav",
                "age": 29,
                "gender": "man",
                "interested_in": "women",
                "city": "Bengaluru",
                "phone": "+919999999999",
            },
        )
        self.assertEqual(save_response.status_code, 200)
        self.assertTrue(save_response.json()["complete"])

        loaded_response = self.client.get("/api/me/dating-basics")
        self.assertEqual(loaded_response.json()["profile"]["display_name"], "Aarav")
        self.assertEqual(loaded_response.json()["profile"]["gender"], "man")
        self.assertEqual(loaded_response.json()["profile"]["interested_in"], "women")
        self.assertEqual(loaded_response.json()["profile"]["city"], "Bengaluru")
        self.assertEqual(loaded_response.json()["profile"]["phone"], "+919999999999")

    def test_profile_photo_upload_updates_user_profile(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        save_response = self.client.put(
            "/api/me/dating-basics",
            json={
                "display_name": "Aarav",
                "age": 29,
                "gender": "man",
                "interested_in": "women",
                "city": "Bengaluru",
            },
        )
        self.assertEqual(save_response.status_code, 200)

        response = self.client.put(
            "/api/me/profile-photo",
            content=b"fake-image-bytes",
            headers={"content-type": "image/png"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["profile_photo_url"].startswith("/uploads/profile_photos/"))
        loaded_response = self.client.get("/api/me/dating-basics")
        self.assertEqual(
            loaded_response.json()["profile"]["profile_photo_url"],
            response.json()["profile_photo_url"],
        )

    def test_profile_photo_slot_upload_preserves_existing_slots(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        save_response = self.client.put(
            "/api/me/dating-basics",
            json={
                "display_name": "Aarav",
                "age": 29,
                "gender": "man",
                "interested_in": "women",
                "city": "Bengaluru",
            },
        )
        self.assertEqual(save_response.status_code, 200)

        first_response = self.client.put(
            "/api/me/profile-photo?slot=0",
            content=b"first-image",
            headers={"content-type": "image/png"},
        )
        self.assertEqual(first_response.status_code, 200)
        first_url = first_response.json()["profile_photo_urls"][0]

        third_response = self.client.put(
            "/api/me/profile-photo?slot=2",
            content=b"third-image",
            headers={"content-type": "image/png"},
        )
        self.assertEqual(third_response.status_code, 200)
        third_urls = third_response.json()["profile_photo_urls"]
        self.assertEqual(third_urls[0], first_url)
        self.assertEqual(third_urls[1], "")
        third_url = third_urls[2]

        second_response = self.client.put(
            "/api/me/profile-photo?slot=1",
            content=b"second-image",
            headers={"content-type": "image/png"},
        )
        self.assertEqual(second_response.status_code, 200)
        second_urls = second_response.json()["profile_photo_urls"]
        self.assertEqual(second_urls[0], first_url)
        self.assertTrue(second_urls[1].startswith("/uploads/profile_photos/"))
        self.assertEqual(second_urls[2], third_url)

    def test_agent_initial_persona_uses_interested_gender(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        self.client.put(
            "/api/me/dating-basics",
            json={
                "display_name": "Aarav",
                "age": 29,
                "gender": "man",
                "interested_in": "women",
                "city": "Bengaluru",
            },
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
            json={
                "age": 29,
                "gender": "man",
                "interested_in": "women",
                "city": "Bengaluru",
            },
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
            json={
                "display_name": "Anaya",
                "age": 28,
                "gender": "woman",
                "interested_in": "men",
                "city": "Mumbai",
            },
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

    def test_data_point_feedback_is_saved_and_returned_with_raw_points(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        fact = upsert_profile_fact(
            {
                "user_id": "user-a",
                "category": "whatsapp_topics",
                "key": "location",
                "value": {"topics": ["location", "voice call"]},
                "label": "Talked about location and a voice call",
                "confidence": 0.74,
                "source_kind": "whatsapp_import",
                "source_id": "source-a",
                "used_for_matching": False,
                "used_for_chat_context": True,
            }
        )

        response = self.client.post(
            f"/api/me/profile-facts/{fact['id']}/feedback",
            json={"rating": "disagree", "reason": "wrong", "comment": "This is too broad."},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["feedback"]["rating"], "disagree")
        self.assertEqual(response.json()["fact"]["status"], "rejected")
        self.assertFalse(response.json()["fact"]["used_for_matching"])
        self.assertFalse(response.json()["fact"]["used_for_chat_context"])
        self.assertLessEqual(response.json()["fact"]["confidence"], 0.2)
        stored_feedback = list_data_point_feedback(user_id="user-a")
        self.assertEqual(len(stored_feedback), 1)
        self.assertEqual(stored_feedback[0]["profile_fact_id"], fact["id"])
        self.assertEqual(stored_feedback[0]["metadata"]["original_fact"]["status"], "active")
        self.assertEqual(
            list_profile_facts("user-a", used_for_chat_context=True),
            [],
        )

        upsert_profile_fact(
            {
                "user_id": "user-a",
                "category": "whatsapp_topics",
                "key": "location",
                "value": {"topics": ["location", "voice call", "meetup"]},
                "label": "Talked about location again",
                "confidence": 0.92,
                "source_kind": "whatsapp_import",
                "source_id": "source-a",
                "used_for_matching": True,
                "used_for_chat_context": True,
            }
        )
        rejected_fact = get_profile_fact(fact["id"], "user-a")
        self.assertEqual(rejected_fact["status"], "rejected")
        self.assertFalse(rejected_fact["used_for_matching"])
        self.assertFalse(rejected_fact["used_for_chat_context"])

        update_response = self.client.post(
            f"/api/me/profile-facts/{fact['id']}/feedback",
            json={"rating": "agree"},
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(len(list_data_point_feedback(user_id="user-a")), 1)
        self.assertEqual(update_response.json()["feedback"]["rating"], "agree")
        self.assertEqual(update_response.json()["fact"]["status"], "active")
        self.assertFalse(update_response.json()["fact"]["used_for_matching"])
        self.assertTrue(update_response.json()["fact"]["used_for_chat_context"])
        self.assertGreaterEqual(update_response.json()["fact"]["confidence"], 0.9)

        with patch.dict("os.environ", {"PROFILE_DEBUG_DATA_ENABLED": "true"}):
            profile_response = self.client.get("/api/me/profile")

        raw_point = profile_response.json()["raw_internal_data_points"][0]
        self.assertEqual(raw_point["id"], fact["id"])
        self.assertEqual(raw_point["feedback"]["rating"], "agree")
        self.assertEqual(profile_response.json()["data_point_feedback_summary"]["agree"], 1)

    def test_data_point_feedback_is_scoped_to_current_user(self) -> None:
        async def user_b() -> CurrentUser:
            return CurrentUser(id="user-b", email="b@example.com")

        fact = upsert_profile_fact(
            {
                "user_id": "user-a",
                "category": "values",
                "key": "kindness",
                "value": {"kind": "important"},
                "label": "Values kindness",
                "confidence": 0.8,
            }
        )

        app.dependency_overrides[current_user] = user_b
        response = self.client.post(
            f"/api/me/profile-facts/{fact['id']}/feedback",
            json={"rating": "agree"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(list_data_point_feedback(), [])

    def test_data_point_extraction_debug_stores_review_decisions(self) -> None:
        saved = save_data_point_extraction_debug(
            {
                "user_id": "user-a",
                "source_kind": "whatsapp_import",
                "source_id": "source-a",
                "import_id": "import-a",
                "candidate_key": "meeting_location_coordination",
                "decision": "rejected",
                "candidate": {
                    "label": "Talked about location",
                    "evidence": ["location kidhar hai"],
                },
                "review": {
                    "decision": "rejected",
                    "reason": "Only a keyword, not useful memory.",
                },
                "metadata": {"reviewer": "llm", "model": "mock"},
            }
        )

        self.assertEqual(saved["decision"], "rejected")
        self.assertEqual(saved["candidate"]["label"], "Talked about location")
        self.assertEqual(saved["review"]["reason"], "Only a keyword, not useful memory.")

        save_data_point_extraction_debug(
            {
                "user_id": "user-b",
                "source_kind": "whatsapp_import",
                "source_id": "source-b",
                "import_id": "import-b",
                "candidate_key": "coffee_plan",
                "decision": "approved",
                "candidate": {"label": "Planned coffee"},
                "review": {"decision": "approved"},
            }
        )

        user_rows = list_data_point_extraction_debug(user_id="user-a")
        rejected_rows = list_data_point_extraction_debug(
            user_id="user-a",
            source_id="source-a",
            decision="rejected",
        )
        approved_rows = list_data_point_extraction_debug(user_id="user-a", decision="approved")

        self.assertEqual(len(user_rows), 1)
        self.assertEqual(rejected_rows[0]["id"], saved["id"])
        self.assertEqual(approved_rows, [])

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

    def test_profile_fact_aliases_merge_at_write_time(self) -> None:
        first = upsert_profile_fact(
            {
                "user_id": "user-a",
                "category": "values",
                "key": "honesty",
                "value": {"kind": "honesty"},
                "label": "Values honesty",
                "confidence": 0.72,
                "evidence": [{"text": "Honesty matters to me."}],
            }
        )
        second = upsert_profile_fact(
            {
                "user_id": "user-a",
                "category": "communication",
                "key": "honest_communication",
                "value": {"kind": "honest_communication"},
                "label": "Prefers honest communication",
                "confidence": 0.86,
                "evidence": [{"text": "I prefer honest communication."}],
            }
        )

        facts = list_profile_facts("user-a")

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["category"], "values")
        self.assertEqual(facts[0]["key"], "honesty")
        self.assertEqual(facts[0]["confidence"], 0.86)
        self.assertEqual(len(facts[0]["evidence"]), 2)

    def test_rejected_profile_fact_alias_stays_rejected_on_duplicate_upsert(self) -> None:
        fact = upsert_profile_fact(
            {
                "user_id": "user-a",
                "category": "values",
                "key": "honesty",
                "value": {"kind": "honesty"},
                "label": "Values honesty",
                "confidence": 0.72,
                "used_for_matching": True,
                "used_for_chat_context": True,
            }
        )
        save_data_point_feedback(
            {
                "user_id": "user-a",
                "profile_fact_id": fact["id"],
                "rating": "disagree",
                "reason": "wrong",
            }
        )

        duplicate = upsert_profile_fact(
            {
                "user_id": "user-a",
                "category": "communication",
                "key": "honest_communication",
                "value": {"kind": "honest_communication"},
                "label": "Prefers honest communication",
                "confidence": 0.95,
                "used_for_matching": True,
                "used_for_chat_context": True,
            }
        )

        self.assertEqual(duplicate["id"], fact["id"])
        self.assertEqual(duplicate["status"], "rejected")
        self.assertFalse(duplicate["used_for_matching"])
        self.assertFalse(duplicate["used_for_chat_context"])
        self.assertLessEqual(duplicate["confidence"], 0.2)

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
            json={
                "display_name": "Aarav",
                "age": 29,
                "gender": "man",
                "interested_in": "women",
                "city": "Bengaluru",
            },
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
        self.assertTrue(
            any(
                fact["category"] == "communication"
                and fact["key"] == "calm_low_drama"
                and "calm" in fact["label"].lower()
                for fact in facts
            )
        )
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
        self.assertIn(("values", "ambition"), fact_keys)
        self.assertIn(("values", "mutual_respect"), fact_keys)

    def test_hybrid_chat_data_point_review_runs_for_deep_conversation_memory(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]

        with patch.dict(
            os.environ,
            {
                "AGENT_PROVIDER": "mock",
                "DATA_POINT_EXTRACTOR": "hybrid",
                "PROFILE_FACT_DEEP_EXTRACT_INTERVAL": "2",
            },
        ):
            for index in range(2):
                response = self.client.post(
                    f"/api/agent/conversations/{conversation_id}/messages",
                    json={
                        "message": (
                            f"Career growth and mutual respect matter to me in dating. "
                            f"Useful detail {index}."
                        )
                    },
                )
                self.assertEqual(response.status_code, 200)

        debug_rows = list_data_point_extraction_debug(user_id="user-a")
        self.assertGreaterEqual(len(debug_rows), 2)
        self.assertTrue(all(row["source_kind"] == "agent_conversation" for row in debug_rows))
        self.assertTrue(all(row["decision"] == "approve" for row in debug_rows))
        self.assertEqual({row["source_id"] for row in debug_rows}, {conversation_id})

        facts = list_profile_facts("user-a")
        fact_keys = {(fact["category"], fact["key"]) for fact in facts}
        self.assertIn(("values", "ambition"), fact_keys)
        self.assertIn(("values", "mutual_respect"), fact_keys)
        reviewed_facts = [
            fact for fact in facts if fact["source_kind"] == "agent_conversation"
        ]
        self.assertTrue(reviewed_facts)

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
        save_agent_message_feedback(
            {
                "user_id": "user-a",
                "conversation_id": conversation_id,
                "message_index": 0,
                "rating": "bad",
                "reason": "bad_tone",
                "comment": "Felt too sharp.",
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
        self.assertEqual(data["summary"]["feedback_count"], 1)
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
        self.assertEqual(len(data["activity"]["daily"]), 14)
        self.assertEqual(data["activity"]["totals"]["new_users"], 1)
        self.assertEqual(data["activity"]["totals"]["active_users"], 1)
        self.assertEqual(data["activity"]["totals"]["conversations"], 1)
        self.assertEqual(data["activity"]["totals"]["api_calls"], 1)
        self.assertEqual(data["users"][0]["user_id"], "user-a")
        self.assertEqual(data["users"][0]["display_name"], "Aarav")
        self.assertEqual(data["users"][0]["usage"]["total_tokens"], 120)
        self.assertEqual(data["users"][0]["feedback_count"], 1)
        self.assertEqual(data["users"][0]["negative_feedback_count"], 1)
        self.assertEqual(data["recent_conversations"][0]["id"], conversation_id)
        self.assertEqual(data["recent_usage_events"][0]["provider"], "groq")

    def test_agent_reply_context_snapshot_is_visible_in_admin_detail(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]
        import_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/whatsapp-import",
            json={
                "title": "Abhishek chat",
                "user_sender": "Aarav",
                "content": sample_whatsapp_export(),
            },
        )
        self.assertEqual(import_response.status_code, 201)
        message_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/messages",
            json={"message": "what topics were in my uploaded whatsapp chat?"},
        )
        self.assertEqual(message_response.status_code, 200)

        snapshots = list_agent_context_snapshots(conversation_id, "user-a")
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["message_index"], 2)
        self.assertGreaterEqual(snapshots[0]["summary"]["included_source_count"], 1)
        self.assertTrue(snapshots[0]["summary"]["used_structured_whatsapp"])
        traces = list_agent_traces(conversation_id, "user-a")
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["status"], "completed")
        self.assertEqual(traces[0]["summary"]["quality_valid"], True)
        trace_steps = list_agent_trace_steps(traces[0]["id"], user_id="user-a")
        self.assertEqual(
            [step["step_name"] for step in trace_steps],
            [
                "input_guardrail",
                "memory_write",
                "retrieval",
                "context_pack",
                "model_call",
                "context_snapshot",
            ],
        )
        self.assertTrue(trace_steps[2]["metadata"]["source_count"] >= 1)
        trace_response = self.client.get(f"/api/agent/conversations/{conversation_id}/traces")
        self.assertEqual(trace_response.status_code, 200)
        self.assertEqual(trace_response.json()["count"], 1)
        self.assertEqual(
            trace_response.json()["traces"][0]["steps"][3]["step_name"],
            "context_pack",
        )

        app.dependency_overrides.clear()
        admin_response = self.client.get("/api/admin/users/user-a")

        self.assertEqual(admin_response.status_code, 200)
        detail = admin_response.json()
        self.assertEqual(detail["context_snapshot_summary"]["total"], 1)
        self.assertEqual(detail["context_snapshots"][0]["conversation_id"], conversation_id)
        self.assertTrue(detail["conversations"][0]["latest_context_snapshot"])
        self.assertEqual(detail["agent_trace_summary"]["total"], 1)
        self.assertEqual(detail["agent_traces"][0]["steps"][4]["step_name"], "model_call")
        self.assertTrue(detail["conversations"][0]["latest_agent_trace"])

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
        save_agent_message_feedback(
            {
                "user_id": "user-a",
                "conversation_id": conversation_a,
                "message_index": 0,
                "rating": "off",
                "reason": "wrong_memory",
                "comment": "This assumed something I never said.",
            }
        )
        save_data_point_extraction_debug(
            {
                "user_id": "user-a",
                "source_kind": "whatsapp_import",
                "source_id": "source-a",
                "import_id": "import-a",
                "candidate_key": "source_a_music",
                "decision": "approve",
                "candidate": {
                    "key": "source_a_music",
                    "label": "Likes music talk",
                    "category": "whatsapp_recurring_topics",
                    "confidence": 0.72,
                    "evidence": ["Aarav: send me that song"],
                },
                "review": {
                    "what_we_learned": "The chat has repeated music hooks.",
                    "why_it_matters": "Useful for softer conversation openings.",
                    "confidence": 0.72,
                    "usage": {"chat_context": True, "matching": False, "style": False},
                    "evidence": ["Aarav: send me that song"],
                },
                "metadata": {"title": "Aarav WhatsApp"},
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
        save_agent_message_feedback(
            {
                "user_id": "user-b",
                "conversation_id": conversation_b,
                "message_index": 0,
                "rating": "good",
            }
        )
        save_data_point_extraction_debug(
            {
                "user_id": "user-b",
                "source_kind": "whatsapp_import",
                "candidate_key": "source_b_reject",
                "decision": "reject",
                "candidate": {"key": "source_b_reject", "label": "Other user"},
                "review": {"rejection_reason": "Not useful."},
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
        self.assertEqual(data["feedback_summary"]["total"], 1)
        self.assertEqual(data["feedback_summary"]["off"], 1)
        self.assertEqual(data["feedback"][0]["user_id"], "user-a")
        self.assertEqual(data["feedback"][0]["conversation_id"], conversation_a)
        self.assertEqual(data["feedback"][0]["rating"], "off")
        self.assertEqual(data["feedback"][0]["reason"], "wrong_memory")
        self.assertEqual(data["feedback"][0]["comment"], "This assumed something I never said.")
        self.assertEqual(data["user"]["data_point_review_count"], 1)
        self.assertEqual(data["data_point_review_summary"]["total"], 1)
        self.assertEqual(data["data_point_review_summary"]["approve"], 1)
        self.assertEqual(data["data_point_reviews"][0]["user_id"], "user-a")
        self.assertEqual(data["data_point_reviews"][0]["decision"], "approve")
        self.assertEqual(
            data["data_point_reviews"][0]["review"]["what_we_learned"],
            "The chat has repeated music hooks.",
        )

    def test_admin_pages_serve_separate_admin_shell(self) -> None:
        response = self.client.get("/admin")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Omiryn Admin", response.text)
        self.assertIn("/admin/static/app.js", response.text)

    def test_app_shell_links_brand_to_app_route(self) -> None:
        response = self.client.get("/app")

        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/app"', response.text)
        self.assertIn("/static/app.js", response.text)

    def test_app_auth_redirect_returns_to_app_route(self) -> None:
        script = (STATIC_DIR / "app.js").read_text()

        self.assertIn("function appReturnUrl()", script)
        self.assertIn("redirectTo: appReturnUrl()", script)
        self.assertNotIn("redirectTo: window.location.origin", script)

    def test_admin_dev_bypass_serves_shell_when_auth_required(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AUTH_REQUIRED": "true",
                "ADMIN_ALLOW_UNAUTHENTICATED_DEV": "true",
                "ADMIN_EMAILS": "",
                "ADMIN_USER_IDS": "",
            },
        ):
            response = self.client.get("/admin")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Omiryn Admin", response.text)

    def test_admin_dev_bypass_overrides_configured_admin_allowlist(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AUTH_REQUIRED": "true",
                "ADMIN_ALLOW_UNAUTHENTICATED_DEV": "true",
                "ADMIN_EMAILS": "admin@example.com",
                "ADMIN_USER_IDS": "admin-user",
            },
        ):
            response = self.client.get("/admin")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Omiryn Admin", response.text)

    def test_admin_api_rejects_non_admin_when_admins_are_configured(self) -> None:
        async def non_admin_user() -> CurrentUser:
            return CurrentUser(id="user-b", email="b@example.com")

        app.dependency_overrides[current_user] = non_admin_user
        with patch.dict(
            "os.environ",
            {
                "AUTH_REQUIRED": "true",
                "ADMIN_ALLOW_UNAUTHENTICATED_DEV": "false",
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
        self.assertIn("api_key_loaded", data)
        self.assertIn("groq_api_key_loaded", data)
        self.assertIn("deepinfra_api_key_loaded", data)
        self.assertIn("fireworks_api_key_loaded", data)
        self.assertNotIn("groq_api_key", data)
        self.assertNotIn("deepinfra_api_key", data)
        self.assertNotIn("fireworks_api_key", data)

    def test_deepinfra_runtime_config_uses_env_key_and_models(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AGENT_PROVIDER": "deepinfra",
                "DEEPINFRA_API_KEY": "deepinfra-test-key",
                "DEEPINFRA_MODEL": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            },
        ):
            status = agent_runtime_status()
            config = _openai_compatible_provider_config("deepinfra", None)

        self.assertEqual(status["provider"], "deepinfra")
        self.assertTrue(status["api_key_loaded"])
        self.assertTrue(status["deepinfra_api_key_loaded"])
        self.assertIn("meta-llama/Llama-3.3-70B-Instruct-Turbo", status["available_models"])
        self.assertEqual(
            config["chat_url"],
            "https://api.deepinfra.com/v1/openai/chat/completions",
        )

    def test_fireworks_runtime_config_uses_env_key_and_models(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AGENT_PROVIDER": "fireworks",
                "FIREWORKS_API_KEY": "fireworks-test-key",
                "FIREWORKS_MODEL": "accounts/fireworks/models/gpt-oss-120b",
            },
        ):
            status = agent_runtime_status()
            config = _openai_compatible_provider_config("fireworks", None)

        self.assertEqual(status["provider"], "fireworks")
        self.assertTrue(status["api_key_loaded"])
        self.assertTrue(status["fireworks_api_key_loaded"])
        self.assertIn("accounts/fireworks/models/gpt-oss-120b", status["available_models"])
        self.assertEqual(
            config["chat_url"],
            "https://api.fireworks.ai/inference/v1/chat/completions",
        )

    def test_provider_cost_estimate_uses_provider_specific_env(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "DEEPINFRA_INPUT_COST_PER_1M": "0.10",
                "DEEPINFRA_OUTPUT_COST_PER_1M": "0.32",
                "FIREWORKS_INPUT_COST_PER_1M": "0.15",
                "FIREWORKS_OUTPUT_COST_PER_1M": "0.60",
            },
        ):
            self.assertEqual(_provider_token_costs("deepinfra"), (0.10, 0.32))
            self.assertEqual(_estimated_cost_usd("deepinfra", 2000, 100), 0.000232)
            self.assertEqual(_estimated_cost_usd("fireworks", 2000, 100), 0.00036)

    def test_auth_config_exposes_provider_settings(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AUTH_PROVIDER": "supabase",
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
                "auth_provider": "supabase",
                "supabase_url": "https://example.supabase.co",
                "supabase_anon_key": "anon-public-key",
                "auth_required": True,
                "auth_gate_required": True,
                "providers": {
                    "supabase": {
                        "url": "https://example.supabase.co",
                        "anon_key": "anon-public-key",
                    }
                },
                "profile_debug_data_enabled": True,
            },
        )

    def test_auth_config_gates_browser_when_provider_is_configured(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AUTH_PROVIDER": "supabase",
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_ANON_KEY": "anon-public-key",
                "AUTH_REQUIRED": "false",
            },
        ):
            response = self.client.get("/api/auth/config")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["auth_required"])
        self.assertTrue(response.json()["auth_gate_required"])

    def test_auth_required_blocks_anonymous_user_data_routes(self) -> None:
        with patch.dict("os.environ", {"AUTH_REQUIRED": "true"}):
            response = self.client.get("/api/agent/conversations")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Sign in to continue.")

    def test_conversation_can_store_selected_model(self) -> None:
        response = self.client.post(
            "/api/agent/conversations",
            json={
                "agent_model": "mock",
                "agent_mode": "coach_me",
                "agent_tone": "casual",
                "agent_name": "Amy",
            },
        )

        self.assertEqual(response.status_code, 201)
        conversation = response.json()
        self.assertEqual(conversation["agent_model"], "mock")
        self.assertEqual(conversation["agent_mode"], "coach_me")
        self.assertEqual(conversation["agent_tone"], "casual")
        self.assertEqual(conversation["agent_name"], "Amy")

        update_response = self.client.patch(
            f"/api/agent/conversations/{conversation['id']}/settings",
            json={
                "agent_model": "mock",
                "agent_mode": "talk_like_me",
                "agent_tone": "direct",
                "agent_name": "Mira",
            },
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["agent_model"], "mock")
        self.assertEqual(update_response.json()["agent_mode"], "talk_like_me")
        self.assertEqual(update_response.json()["agent_tone"], "direct")
        self.assertEqual(update_response.json()["agent_name"], "Mira")

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
        self.assertEqual(list_response.json()["count"], 0)
        self.assertEqual(len(list_response.json()["available_sources"]), 1)
        self.assertFalse(list_response.json()["available_sources"][0]["attached"])

        history_response = self.client.get("/api/agent/conversations")
        self.assertEqual(history_response.json()["conversations"][0]["context_source_count"], 0)

        attach_response = self.client.put(
            f"/api/agent/conversations/{conversation_id}/context-sources/attachments",
            json={"source_ids": [created["id"]]},
        )
        self.assertEqual(attach_response.status_code, 200)
        self.assertEqual(attach_response.json()["count"], 1)
        self.assertTrue(attach_response.json()["available_sources"][0]["attached"])

        history_response = self.client.get("/api/agent/conversations")
        self.assertEqual(history_response.json()["conversations"][0]["context_source_count"], 1)

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

    def test_orphan_attached_context_does_not_count_in_history(self) -> None:
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]
        source_id = self.client.post(
            f"/api/agent/conversations/{conversation_id}/context-sources",
            json={
                "source_type": "llm_profile",
                "title": "Temporary memory",
                "content": "The user values calm communication and career growth.",
            },
        ).json()["id"]
        attach_response = self.client.put(
            f"/api/agent/conversations/{conversation_id}/context-sources/attachments",
            json={"source_ids": [source_id]},
        )
        self.assertEqual(attach_response.json()["count"], 1)

        delete_response = self.client.delete(
            f"/api/agent/conversations/{conversation_id}/context-sources/{source_id}"
        )
        self.assertEqual(delete_response.status_code, 200)

        history_response = self.client.get("/api/agent/conversations")
        self.assertEqual(history_response.json()["conversations"][0]["context_source_count"], 0)
        list_response = self.client.get(f"/api/agent/conversations/{conversation_id}/context-sources")
        self.assertEqual(list_response.json()["count"], 0)
        self.assertEqual(list_response.json()["available_sources"], [])

    def test_user_context_delete_removes_reusable_source_and_attached_copies(self) -> None:
        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = signed_in_user
        first_conversation_id = self.client.post("/api/agent/conversations").json()["id"]
        source_id = self.client.post(
            f"/api/agent/conversations/{first_conversation_id}/context-sources",
            json={
                "source_type": "llm_profile",
                "title": "Delete me",
                "content": "The user values calm communication and ambition.",
            },
        ).json()["id"]
        second_conversation_id = self.client.post("/api/agent/conversations").json()["id"]
        self.client.put(
            f"/api/agent/conversations/{second_conversation_id}/context-sources/attachments",
            json={"source_ids": [source_id]},
        )

        delete_response = self.client.delete(
            f"/api/agent/conversations/{second_conversation_id}/context-sources/{source_id}"
        )

        self.assertEqual(delete_response.status_code, 200)
        first_sources = self.client.get(
            f"/api/agent/conversations/{first_conversation_id}/context-sources"
        ).json()
        second_sources = self.client.get(
            f"/api/agent/conversations/{second_conversation_id}/context-sources"
        ).json()
        self.assertEqual(first_sources["count"], 0)
        self.assertEqual(first_sources["available_sources"], [])
        self.assertEqual(second_sources["count"], 0)
        self.assertEqual(second_sources["available_sources"], [])

    def test_reply_context_ignores_unattached_imports(self) -> None:
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

        sources = _smart_reply_context_sources(
            conversation_id,
            None,
            "what do you know about my career from imported memory?",
        )

        self.assertEqual(sources, [])

    def test_reply_context_retrieves_relevant_imported_memory(self) -> None:
        conversation_response = self.client.post("/api/agent/conversations")
        conversation_id = conversation_response.json()["id"]
        career_response = self.client.post(
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
        self.client.put(
            f"/api/agent/conversations/{conversation_id}/context-sources/attachments",
            json={"source_ids": [career_response.json()["id"]]},
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
        self.assertEqual(list_response.json()["count"], 0)
        self.assertEqual(len(list_response.json()["available_sources"]), 1)
        self.assertFalse(list_response.json()["available_sources"][0]["attached"])

    def test_whatsapp_import_stores_structured_phase_one_memory(self) -> None:
        conversation_response = self.client.post("/api/agent/conversations")
        conversation_id = conversation_response.json()["id"]

        create_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/whatsapp-import",
            json={
                "title": "Abhishek chat",
                "user_sender": "Aarav",
                "content": sample_whatsapp_export(),
            },
        )

        self.assertEqual(create_response.status_code, 201)
        source_id = create_response.json()["id"]
        imports = list_whatsapp_imports(conversation_id)
        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0]["context_source_id"], source_id)
        self.assertEqual(imports[0]["selected_sender"], "Aarav")
        self.assertEqual(imports[0]["metadata"]["parsed_message_count"], 6)
        self.assertTrue(imports[0]["metadata"]["embedding_ready"])
        self.assertEqual(imports[0]["metadata"]["embedding_kind"], "local_hash_v1")

        messages = list_whatsapp_messages(imports[0]["id"])
        self.assertEqual(len(messages), 6)
        self.assertEqual(messages[0]["sender"], "Aarav")
        self.assertEqual(messages[0]["timestamp_text"], "12/06/2026 10:00 AM")
        self.assertIn("running late", messages[0]["content"])
        self.assertIn("second line", messages[2]["content"])

        chunks = list_whatsapp_chunks(imports[0]["id"])
        self.assertGreaterEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["chunk_index"], 1)
        self.assertEqual(chunks[0]["embedding"]["kind"], "local_hash_v1")
        self.assertIn("Aarav:", chunks[0]["content"])
        self.assertIn("Riya:", chunks[0]["content"])

        people = list_whatsapp_people(imports[0]["id"])
        self.assertEqual({person["sender"] for person in people}, {"Aarav", "Riya"})
        self.assertEqual(
            next(person for person in people if person["sender"] == "Aarav")["role"],
            "selected_user",
        )

        style_profiles = list_whatsapp_style_profiles(imports[0]["id"])
        self.assertEqual({profile["sender"] for profile in style_profiles}, {"Aarav", "Riya"})
        aarav_style = next(profile for profile in style_profiles if profile["sender"] == "Aarav")
        self.assertIn("average_words", aarav_style["summary"])
        self.assertIn("topic_terms", aarav_style["summary"])
        self.assertTrue(aarav_style["sample_messages"])

    def test_reply_context_retrieves_structured_whatsapp_memory_when_relevant(self) -> None:
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]
        create_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/whatsapp-import",
            json={
                "title": "Abhishek chat",
                "user_sender": "Aarav",
                "content": sample_whatsapp_export(),
            },
        )
        self.assertEqual(create_response.status_code, 201)

        casual_sources = _smart_reply_context_sources(conversation_id, None, "haan okay")
        self.assertEqual(casual_sources, [])

        whatsapp_sources = _smart_reply_context_sources(
            conversation_id,
            None,
            "what do you know from my whatsapp messages about coffee plan?",
        )

        self.assertGreaterEqual(len(whatsapp_sources), 1)
        structured_source = next(
            source
            for source in whatsapp_sources
            if source["source_type"] == "whatsapp_structured_context"
        )
        self.assertIn("Structured WhatsApp context", structured_source["content"])
        self.assertIn("People:", structured_source["content"])
        self.assertIn("Style adaptation guides:", structured_source["content"])
        self.assertIn("Sender style profile metrics:", structured_source["content"])
        self.assertIn("coffee first", structured_source["content"])

    def test_reply_context_semantically_ranks_whatsapp_chunks(self) -> None:
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]
        create_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/whatsapp-import",
            json={
                "title": "Abhishek chat",
                "user_sender": "Sourabh",
                "content": sample_multi_chunk_whatsapp_export(),
            },
        )
        self.assertEqual(create_response.status_code, 201)

        whatsapp_sources = _smart_reply_context_sources(
            conversation_id,
            None,
            "where did abhishek ask me to wait?",
        )

        structured_source = next(
            source
            for source in whatsapp_sources
            if source["source_type"] == "whatsapp_structured_context"
        )
        relevant_chunks = structured_source["content"].split("Relevant message chunks:", 1)[1]
        first_chunk = relevant_chunks.split("Chunk ", 2)[1]
        self.assertIn("wahi per rukna", first_chunk)
        self.assertNotIn("movie playlist filler 01", first_chunk)

    def test_whatsapp_import_creates_chat_data_points_for_authenticated_user(self) -> None:
        async def user_a() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = user_a
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]
        create_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/whatsapp-import",
            json={
                "title": "Abhishek chat",
                "user_sender": "Aarav",
                "content": sample_whatsapp_export(),
            },
        )
        self.assertEqual(create_response.status_code, 201)
        source_id = create_response.json()["id"]

        facts = list_profile_facts("user-a")
        categories = {fact["category"] for fact in facts}
        self.assertIn("whatsapp_recurring_topics", categories)
        self.assertIn("whatsapp_recent_events", categories)
        self.assertIn("whatsapp_tone_traits", categories)
        self.assertNotIn("whatsapp_topics", categories)
        self.assertTrue(all(fact["source_kind"] == "whatsapp_import" for fact in facts))
        self.assertTrue(all(fact["source_id"] == source_id for fact in facts))
        self.assertTrue(all(fact["used_for_chat_context"] for fact in facts))
        self.assertTrue(all(not fact["used_for_matching"] for fact in facts))
        self.assertTrue(all((fact["value"] or {}).get("meaning") for fact in facts))
        self.assertFalse(any("WhatsApp topics include" in fact["label"] for fact in facts))

        sources = _smart_reply_context_sources(
            conversation_id,
            None,
            "what topics were in my uploaded whatsapp chat?",
            "user-a",
        )
        data_point_source = next(
            source for source in sources if source["source_type"] == "data_points"
        )
        self.assertEqual(sources[0]["source_type"], "whatsapp_structured_context")
        self.assertIn("whatsapp", sources[0]["metadata"]["query_intent"])
        self.assertIn("WhatsApp chat makes casual plans", data_point_source["content"])

        style_sources = _smart_reply_context_sources(
            conversation_id,
            None,
            "can you talk in Aarav tone?",
            "user-a",
        )
        self.assertEqual(style_sources[0]["source_type"], "whatsapp_structured_context")
        self.assertIn("style", style_sources[0]["metadata"]["query_intent"])

        generic_sources = _smart_reply_context_sources(
            conversation_id,
            None,
            "what do you know about my preferences?",
            "user-a",
        )
        self.assertEqual(generic_sources[0]["source_type"], "data_points")

    def test_whatsapp_import_can_use_llm_data_point_extractor(self) -> None:
        async def user_a() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = user_a
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]
        with patch.dict("os.environ", {"DATA_POINT_EXTRACTOR": "llm"}):
            create_response = self.client.post(
                f"/api/agent/conversations/{conversation_id}/whatsapp-import",
                json={
                    "title": "Riya chat",
                    "user_sender": "Aarav",
                    "content": sample_whatsapp_export(),
                },
            )

        self.assertEqual(create_response.status_code, 201)
        facts = list_profile_facts("user-a")
        self.assertTrue(facts)
        self.assertIn("recent_events", {fact["category"] for fact in facts})
        self.assertTrue(all((fact["value"] or {}).get("extractor") == "llm" for fact in facts))

    def test_whatsapp_import_hybrid_reviews_rule_candidates(self) -> None:
        async def user_a() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = user_a
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]
        with patch.dict("os.environ", {"DATA_POINT_EXTRACTOR": "hybrid"}):
            create_response = self.client.post(
                f"/api/agent/conversations/{conversation_id}/whatsapp-import",
                json={
                    "title": "Riya chat",
                    "user_sender": "Aarav",
                    "content": sample_whatsapp_export(),
                },
            )

        self.assertEqual(create_response.status_code, 201)
        facts = list_profile_facts("user-a")
        debug_rows = list_data_point_extraction_debug(user_id="user-a")

        self.assertTrue(facts)
        self.assertTrue(debug_rows)
        self.assertTrue(
            all((fact["value"] or {}).get("extractor") == "hybrid_llm_review" for fact in facts)
        )
        self.assertIn("whatsapp_recurring_topics", {fact["category"] for fact in facts})
        self.assertTrue(all(row["candidate"]["source"] == "rules" for row in debug_rows))
        self.assertTrue(all(row["review"]["decision"] in {"approve", "rewrite", "merge", "reject"} for row in debug_rows))

    def test_whatsapp_source_delete_removes_data_point_debug_rows(self) -> None:
        async def user_a() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = user_a
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]
        create_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/whatsapp-import",
            json={
                "title": "Abhishek chat",
                "user_sender": "Aarav",
                "content": sample_whatsapp_export(),
            },
        )
        source_id = create_response.json()["id"]
        import_id = list_whatsapp_imports(user_id="user-a")[0]["id"]
        save_data_point_extraction_debug(
            {
                "user_id": "user-a",
                "source_kind": "whatsapp_import",
                "source_id": source_id,
                "import_id": import_id,
                "candidate_key": "coffee_plan",
                "decision": "approved",
                "candidate": {"label": "Planned coffee"},
                "review": {"decision": "approved"},
            }
        )

        self.assertEqual(len(list_data_point_extraction_debug(user_id="user-a")), 1)
        delete_response = self.client.delete(
            f"/api/agent/conversations/{conversation_id}/context-sources/{source_id}"
        )

        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(list_data_point_extraction_debug(user_id="user-a"), [])

    def test_selected_style_source_packs_structured_whatsapp_context(self) -> None:
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]
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
        style_source_id = create_response.json()["id"]

        sources = _smart_reply_context_sources(
            conversation_id,
            style_source_id,
            "haan okay",
        )

        self.assertEqual(sources[0]["source_type"], "friend_style")
        structured_source = next(
            source for source in sources if source["source_type"] == "whatsapp_structured_context"
        )
        self.assertIn("Style adaptation guide for Aarav (selected)", structured_source["content"])
        self.assertIn("Do not claim to be this sender", structured_source["content"])

    def test_attached_whatsapp_source_packs_structured_memory_in_new_chat(self) -> None:
        first_conversation_id = self.client.post("/api/agent/conversations").json()["id"]
        create_response = self.client.post(
            f"/api/agent/conversations/{first_conversation_id}/whatsapp-import",
            json={
                "title": "Abhishek chat",
                "user_sender": "Aarav",
                "content": sample_whatsapp_export(),
            },
        )
        self.assertEqual(create_response.status_code, 201)
        source_id = create_response.json()["id"]

        second_conversation_id = self.client.post("/api/agent/conversations").json()["id"]
        attach_response = self.client.put(
            f"/api/agent/conversations/{second_conversation_id}/context-sources/attachments",
            json={"source_ids": [source_id]},
        )
        self.assertEqual(attach_response.status_code, 200)

        sources = _smart_reply_context_sources(
            second_conversation_id,
            None,
            "what topics were in my uploaded whatsapp chat?",
        )

        self.assertTrue(
            any(source["source_type"] == "whatsapp_structured_context" for source in sources)
        )

    def test_large_whatsapp_import_uses_latest_complete_messages(self) -> None:
        old_message = "01/01/2026, 10:00 AM - Aarav: old context that should be dropped\n"
        latest_export = "\n".join(
            f"12/06/2026, 10:{minute:02d} AM - Aarav: latest message {minute}"
            if minute % 2 == 0
            else f"12/06/2026, 10:{minute:02d} AM - Riya: latest reply {minute}"
            for minute in range(6)
        )
        export_text = old_message * 10 + latest_export

        with patch("ingestion.whatsapp.WHATSAPP_IMPORT_MAX_CHARS", len(latest_export) + 5):
            prepared_text, metadata = prepare_whatsapp_export_text(export_text)
            messages = parse_whatsapp_export(prepared_text)
            structured = build_whatsapp_structured_memory(export_text, "Aarav")
            summary = build_whatsapp_style_summary(export_text, "Aarav")

        self.assertTrue(metadata["truncated"])
        self.assertEqual(metadata["truncation_strategy"], "latest_complete_messages")
        self.assertTrue(prepared_text.startswith("12/06/2026"))
        self.assertGreaterEqual(len(messages), 6)
        self.assertTrue(structured.metadata["truncated"])
        self.assertEqual(structured.metadata["original_char_count"], len(export_text))
        self.assertIn("Large export note", summary.content)
        self.assertTrue(summary.metadata["truncated"])

    def test_whatsapp_structured_memory_is_removed_with_source(self) -> None:
        async def user_a() -> CurrentUser:
            return CurrentUser(id="user-a", email="a@example.com")

        app.dependency_overrides[current_user] = user_a
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]
        create_response = self.client.post(
            f"/api/agent/conversations/{conversation_id}/whatsapp-import",
            json={
                "title": "Abhishek chat",
                "user_sender": "Aarav",
                "content": sample_whatsapp_export(),
            },
        )
        self.assertEqual(create_response.status_code, 201)
        source_id = create_response.json()["id"]
        self.assertEqual(len(list_whatsapp_imports(conversation_id)), 1)
        self.assertTrue(list_profile_facts("user-a"))

        delete_response = self.client.delete(
            f"/api/agent/conversations/{conversation_id}/context-sources/{source_id}"
        )

        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(list_whatsapp_imports(conversation_id), [])
        self.assertEqual(list_profile_facts("user-a"), [])

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
        self.assertEqual(messages[0].timestamp_text, "12/06/2026 10:00 AM")
        self.assertIn("second line", messages[2].content)

        summary = build_whatsapp_style_summary(sample_whatsapp_export(), "Aarav")
        self.assertEqual(summary.metadata["selected_sender"], "Aarav")
        self.assertFalse(summary.metadata["raw_chat_stored"])
        self.assertIn("User messages analyzed: 3", summary.content)
        self.assertIn("Recent chat context", summary.content)
        self.assertIn("Last parsed sender: Riya", summary.content)
        self.assertIn("Recent topic terms:", summary.content)

        structured = build_whatsapp_structured_memory(sample_whatsapp_export(), "Aarav")
        self.assertEqual(len(structured.messages), 6)
        self.assertGreaterEqual(len(structured.chunks), 1)
        self.assertEqual(structured.people[0].sender, "Aarav")
        self.assertEqual(structured.people[0].role, "selected_user")
        self.assertEqual({profile.sender for profile in structured.style_profiles}, {"Aarav", "Riya"})
        self.assertTrue(structured.metadata["embedding_ready"])
        self.assertEqual(structured.chunks[0].embedding["kind"], "local_hash_v1")

    def test_whatsapp_parser_supports_bracketed_seconds_export(self) -> None:
        messages = parse_whatsapp_export(sample_bracketed_whatsapp_export())

        self.assertEqual(len(messages), 5)
        self.assertEqual(messages[0].sender, "Sourabh sahu")
        self.assertEqual(messages[0].timestamp_text, "22/05/26 4:44:11 PM")
        self.assertEqual(messages[2].sender, "abhishek")
        self.assertIn("6-7 bje around", messages[2].content)
        self.assertIn("wahi per", messages[4].content)

        structured = build_whatsapp_structured_memory(sample_bracketed_whatsapp_export(), "Sourabh sahu")
        self.assertEqual(len(structured.messages), 5)
        self.assertEqual({person.sender for person in structured.people}, {"Sourabh sahu", "abhishek"})

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


def sample_bracketed_whatsapp_export() -> str:
    return """[22/05/26, 4:44:11 PM] Sourabh sahu: thik h
[22/05/26, 4:44:18 PM] Sourabh sahu: kab chalega?
[22/05/26, 4:53:43 PM] abhishek: vhi 6-7 bje around
[22/05/26, 4:55:19 PM] Sourabh sahu: hmm
[22/05/26, 4:55:54 PM] Sourabh sahu: mai tujhe wahi aaya tha na tu wahi per
wahi per rukna"""


def sample_multi_chunk_whatsapp_export() -> str:
    lines = [
        f"12/06/2026, 9:{minute:02d} AM - Sourabh: movie playlist filler {minute:02d}"
        if minute % 2
        else f"12/06/2026, 9:{minute:02d} AM - Abhishek: song scene filler {minute:02d}"
        for minute in range(1, 25)
    ]
    lines.extend(
        [
            "12/06/2026, 10:25 AM - Sourabh: mai aa gaya hu",
            "12/06/2026, 10:26 AM - Abhishek: voice call kar le pehle",
            "12/06/2026, 10:27 AM - Sourabh: location kidhar hai?",
            "12/06/2026, 10:28 AM - Abhishek: wahi per rukna gate ke paas",
            "12/06/2026, 10:29 AM - Sourabh: thik h wahi wait kar raha hu",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    unittest.main()
