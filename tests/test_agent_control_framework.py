import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.data_point_extraction import (
    build_data_point_review_prompt,
    normalize_llm_data_point_reviews,
    normalize_llm_data_points,
)
from agent.data_points import normalize_data_point, rank_data_points_for_context
from agent.context_budget import budget_context_sources
from agent.profile_facts import extract_profile_facts_from_message
from agent.prompt_builder import build_companion_system_prompt, context_sources_text
from agent.style_adapter import style_adaptation_guide
from agent.whatsapp_data_points import (
    extract_whatsapp_data_point_candidates,
    extract_whatsapp_data_points,
)
from api.main import app
from ingestion.whatsapp import build_whatsapp_structured_memory
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

    def test_dating_intent_requires_specific_outcome(self) -> None:
        generic_facts = extract_profile_facts_from_message(
            "user-a",
            "conversation-a",
            "I am looking for someone special and want a good partner.",
            0,
        )
        specific_facts = extract_profile_facts_from_message(
            "user-a",
            "conversation-a",
            "I want something serious and long-term, maybe marriage.",
            1,
        )

        self.assertNotIn(
            ("dating_intent", "relationship_intent"),
            {(fact["category"], fact["key"]) for fact in generic_facts},
        )
        self.assertIn(
            ("dating_intent", "relationship_intent"),
            {(fact["category"], fact["key"]) for fact in specific_facts},
        )

    def test_whatsapp_data_points_require_meaningful_memory(self) -> None:
        memory = build_whatsapp_structured_memory(
            """12/06/2026, 10:00 AM - Aarav: hey I am running late but I will call you
12/06/2026, 10:01 AM - Riya: no problem
12/06/2026, 10:02 AM - Aarav: also I was thinking about that plan
12/06/2026, 10:03 AM - Riya: what plan?
12/06/2026, 10:04 AM - Aarav: coffee first, then walk?
12/06/2026, 10:05 AM - Riya: okay""",
            "Aarav",
        )

        points = extract_whatsapp_data_points(
            memory,
            user_id="user-a",
            source_id="source-a",
            import_id="import-a",
            title="Riya chat",
        )

        labels = [point["label"] for point in points]
        categories = {point["category"] for point in points}
        self.assertIn("whatsapp_recurring_topics", categories)
        self.assertIn("whatsapp_recent_events", categories)
        self.assertFalse(any("topics include" in label.lower() for label in labels))
        self.assertTrue(any("casual plans" in label for label in labels))
        self.assertTrue(all((point["value"] or {}).get("meaning") for point in points))
        self.assertTrue(all((point["value"] or {}).get("rule_candidate") for point in points))

    def test_whatsapp_relationship_intent_skips_generic_dating_defaults(self) -> None:
        generic_memory = build_whatsapp_structured_memory(
            """12/06/2026, 10:00 AM - Aarav: I am looking for someone special
12/06/2026, 10:01 AM - Riya: what kind?
12/06/2026, 10:02 AM - Aarav: someone good for dating
12/06/2026, 10:03 AM - Riya: okay""",
            "Aarav",
        )
        specific_memory = build_whatsapp_structured_memory(
            """12/06/2026, 10:00 AM - Aarav: I want serious commitment
12/06/2026, 10:01 AM - Riya: like marriage?
12/06/2026, 10:02 AM - Aarav: yes shaadi or long term only
12/06/2026, 10:03 AM - Riya: got it""",
            "Aarav",
        )

        generic_candidates = extract_whatsapp_data_point_candidates(
            generic_memory,
            source_id="source-a",
            title="Riya chat",
        )
        specific_candidates = extract_whatsapp_data_point_candidates(
            specific_memory,
            source_id="source-b",
            title="Riya chat",
        )

        self.assertFalse(
            any((candidate["value"] or {}).get("topic_key") == "relationship_intent" for candidate in generic_candidates)
        )
        self.assertTrue(
            any((candidate["value"] or {}).get("topic_key") == "relationship_intent" for candidate in specific_candidates)
        )

    def test_whatsapp_rules_can_return_reviewable_draft_candidates(self) -> None:
        memory = build_whatsapp_structured_memory(
            """12/06/2026, 10:00 AM - Aarav: hey I am running late but I will call you
12/06/2026, 10:02 AM - Aarav: also I was thinking about that plan
12/06/2026, 10:04 AM - Aarav: coffee first, then walk?
12/06/2026, 10:05 AM - Riya: okay""",
            "Aarav",
        )

        candidates = extract_whatsapp_data_point_candidates(
            memory,
            source_id="source-a",
            title="Riya chat",
        )

        self.assertTrue(candidates)
        self.assertTrue(all(candidate["source"] == "rules" for candidate in candidates))
        self.assertTrue(all(candidate["meaning"] for candidate in candidates))
        self.assertTrue(all(candidate["evidence"] for candidate in candidates))
        self.assertTrue(all("usage" in candidate for candidate in candidates))

    def test_llm_data_point_validator_rejects_keyword_dump_points(self) -> None:
        points = normalize_llm_data_points(
            {
                "data_points": [
                    {
                        "category": "conversation_context",
                        "key": "location",
                        "label": "Talked about location",
                        "meaning": "Too generic",
                        "confidence": 0.9,
                        "evidence": ["location"],
                    },
                    {
                        "category": "relationship_intent",
                        "key": "looking_for_someone_special",
                        "label": "Looking for someone special",
                        "meaning": "Too obvious for a dating app.",
                        "confidence": 0.83,
                        "evidence": ["looking for someone special"],
                    },
                    {
                        "category": "dating_intent",
                        "key": "marriage_oriented",
                        "label": "Marriage-oriented dating intent",
                        "meaning": "Useful for matching toward serious relationship outcomes.",
                        "value": {"kind": "marriage"},
                        "confidence": 0.82,
                        "evidence": ["shaadi or long term only"],
                        "used_for_matching": True,
                    },
                    {
                        "category": "recent_events",
                        "key": "coffee_then_walk",
                        "label": "Planned coffee then a walk",
                        "meaning": "Useful when user asks what the concrete recent plan was.",
                        "value": {"kind": "coffee_then_walk"},
                        "confidence": 0.82,
                        "evidence": ["coffee first, then walk?"],
                        "used_for_chat_context": True,
                    },
                ]
            },
            "user-a",
            "source-a",
            "import-a",
            "Riya chat",
        )

        self.assertEqual(len(points), 2)
        self.assertEqual({point["key"] for point in points}, {"coffee_then_walk", "marriage_oriented"})
        self.assertTrue(all(point["value"]["extractor"] == "llm" for point in points))

    def test_data_point_review_prompt_contains_candidates_and_context(self) -> None:
        memory = build_whatsapp_structured_memory(
            "12/06/2026, 10:04 AM - Aarav: coffee first, then walk?",
            "Aarav",
        )
        candidates = [
            {
                "key": "coffee_plan",
                "label": "Planned coffee then a walk",
                "meaning": "Useful for recent plan context.",
                "evidence": ["coffee first, then walk?"],
            }
        ]

        prompt = build_data_point_review_prompt(memory, candidates, "Riya chat")
        payload = json.loads(prompt)

        self.assertEqual(payload["source_title"], "Riya chat")
        self.assertEqual(payload["candidates"][0]["key"], "coffee_plan")
        self.assertIn("coffee first, then walk", payload["source_excerpt"])

    def test_llm_review_parser_handles_approve_rewrite_and_reject(self) -> None:
        candidates = [
            {
                "key": "coffee_plan",
                "category": "whatsapp_recent_events",
                "label": "Recent WhatsApp context involved coffee and walk",
                "meaning": "Useful for recent plan context.",
                "value": {"kind": "whatsapp_recent_coordination"},
                "confidence": 0.74,
                "evidence": ["coffee first, then walk?"],
                "usage": {"chat_context": True, "matching": False, "style": False},
            },
            {
                "key": "location_keyword",
                "category": "conversation_context",
                "label": "Talked about location",
                "meaning": "Too generic",
                "confidence": 0.72,
                "evidence": ["location"],
            },
            {
                "key": "tone",
                "category": "whatsapp_tone_traits",
                "label": "Aarav's WhatsApp style is brief",
                "meaning": "Useful for adapting reply rhythm.",
                "confidence": 0.7,
                "evidence": ["Aarav: okay"],
                "usage": {"chat_context": True, "style": True},
            },
        ]
        reviews = normalize_llm_data_point_reviews(
            {
                "reviews": [
                    {
                        "candidate_key": "coffee_plan",
                        "decision": "approve",
                        "what_we_learned": "They planned coffee then a walk.",
                        "why_it_matters": "Useful for last-plan questions.",
                        "confidence": 0.82,
                        "evidence": ["coffee first, then walk?"],
                        "usage": {"chat_context": True},
                    },
                    {
                        "candidate_key": "location_keyword",
                        "decision": "reject",
                        "rejection_reason": "Only a keyword, not useful memory.",
                    },
                    {
                        "candidate_key": "tone",
                        "decision": "rewrite",
                        "what_we_learned": "Aarav uses very short replies.",
                        "why_it_matters": "Useful for style adaptation.",
                        "confidence": 0.78,
                        "evidence": ["Aarav: okay"],
                        "usage": {"chat_context": True, "style": True},
                        "final_point": {
                            "category": "communication_style",
                            "key": "short_whatsapp_replies",
                            "label": "Uses short WhatsApp replies",
                            "meaning": "Useful for adapting reply length.",
                            "value": {"kind": "short_whatsapp_replies"},
                        },
                    },
                ]
            },
            candidates,
            "user-a",
            "source-a",
            "import-a",
            "Riya chat",
        )

        self.assertEqual([review["decision"] for review in reviews], ["approve", "reject", "rewrite"])
        self.assertIsNotNone(reviews[0]["point"])
        self.assertEqual(reviews[0]["point"]["value"]["extractor"], "hybrid_llm_review")
        self.assertIsNone(reviews[1]["point"])
        self.assertEqual(reviews[1]["review"]["rejection_reason"], "Only a keyword, not useful memory.")
        self.assertEqual(reviews[2]["point"]["key"], "short_whatsapp_replies")
        self.assertTrue(reviews[2]["point"]["value"]["used_for_style"])

    def test_llm_review_parser_rejects_invalid_reviews(self) -> None:
        candidates = [
            {
                "key": "weak",
                "label": "Weak candidate",
                "meaning": "Maybe useful.",
                "evidence": ["maybe"],
            }
        ]

        reviews = normalize_llm_data_point_reviews(
            {
                "reviews": [
                    {"candidate_key": "missing", "decision": "approve"},
                    {"candidate_key": "weak", "decision": "reject"},
                    {"candidate_key": "weak", "decision": "rewrite", "evidence": ["maybe"]},
                ]
            },
            candidates,
            "user-a",
            "source-a",
            "import-a",
            "Riya chat",
        )

        self.assertEqual(reviews, [])

    def test_context_budget_prefers_compact_memory_and_style(self) -> None:
        budgeted = budget_context_sources(
            [
                {
                    "source_type": "manual_notes",
                    "title": "Long notes",
                    "content": "manual " * 600,
                },
                {
                    "source_type": "whatsapp_structured_context",
                    "title": "Raw chunks",
                    "content": "chunk " * 700,
                },
                {
                    "source_type": "data_points",
                    "title": "Relevant data points",
                    "content": "topic coffee plan tone casual",
                },
                {
                    "source_type": "friend_style",
                    "title": "Abhishek style",
                    "content": "short casual hinglish " * 30,
                },
            ],
            total_budget=1300,
            source_limit=3,
        )

        source_types = [item.source["source_type"] for item in budgeted]
        self.assertIn("data_points", source_types)
        self.assertIn("friend_style", source_types)
        self.assertNotIn("manual_notes", source_types)

    def test_context_text_uses_total_budget(self) -> None:
        context_text = context_sources_text(
            [
                {
                    "source_type": "data_points",
                    "title": "Relevant data points",
                    "content": "points " * 500,
                },
                {
                    "source_type": "whatsapp_structured_context",
                    "title": "Structured WhatsApp context",
                    "content": "chunks " * 900,
                },
                {
                    "source_type": "manual_notes",
                    "title": "Manual",
                    "content": "manual " * 900,
                },
            ]
        )

        self.assertIn("[data_points] Relevant data points", context_text)
        self.assertIn("[whatsapp_structured_context] Structured WhatsApp context", context_text)
        self.assertLess(len(context_text), 5900)

    def test_style_adapter_turns_metrics_into_reply_guidance(self) -> None:
        guide = style_adaptation_guide(
            {
                "sender": "Abhishek",
                "summary": {
                    "average_words": 3.2,
                    "short_message_share": "80%",
                    "question_share": "12%",
                    "exclamation_share": "0%",
                    "emoji_like_share": "0%",
                    "lowercase_opening_share": "70%",
                    "frequent_terms": ["haan", "thik", "wahi"],
                },
                "metadata": {"role": "participant"},
            },
            selected=True,
        )

        self.assertIn("Style adaptation guide for Abhishek (selected)", guide)
        self.assertIn("Prefer 3-8 words", guide)
        self.assertIn("Lowercase openings are acceptable", guide)
        self.assertIn("Do not claim to be this sender", guide)

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
