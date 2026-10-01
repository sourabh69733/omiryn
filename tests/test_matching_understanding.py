import unittest
from datetime import datetime, timedelta, timezone

from agent.context_engine.engine import build_model_context_package
from agent.context_engine.conversation_engine.planning import build_conversation_plan
from agent.context_engine.contracts.models import ContextQueryIntent, ConversationalStance, EmotionState
from agent.context_engine.assembly.matching import (
    MATCHING_DIMENSIONS,
    build_matching_understanding,
    calculate_matching_understanding,
)
from agent.context_engine.prompt_engine.modules.matching_understanding import (
    matching_understanding_prompt,
)
from agent.memory_engine.memories.vibe import (
    BASIC_AREA_IDS,
    line_strength,
    DEEPER_AREA_IDS,
    VIBE_AREA_IDS,
    merge_vibe,
    validate_vibe_updates,
    vibe_progress,
)
from storage import get_vibe_card, reset_db, save_conversation, update_vibe_card

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def line(text: str, messages: int = 2, conversation_id: str = "c1") -> dict:
    """A vibe line backed by `messages` distinct user messages (2+ is clear)."""
    return {
        "text": text,
        "evidence": [{"conversation_id": conversation_id, "message_index": i} for i in range(messages)],
    }


def lines(*area_ids: str, messages: int = 2) -> dict[str, dict]:
    return {area_id: line(f"Line about {area_id}.", messages) for area_id in area_ids}


def resolve_any(ref):
    return ("c1", ref) if isinstance(ref, int) and ref in {1, 3, 5} else None


class VibeProgressTest(unittest.TestCase):
    def test_milestones_follow_filled_areas(self) -> None:
        self.assertEqual(vibe_progress({}).milestone, "starting")
        self.assertEqual(vibe_progress(lines("humor")).milestone, "starting")
        self.assertEqual(vibe_progress(lines("humor", "values")).milestone, "first_impressions")
        self.assertEqual(vibe_progress(lines(*BASIC_AREA_IDS)).milestone, "basics")
        self.assertEqual(
            vibe_progress(lines(*BASIC_AREA_IDS, *DEEPER_AREA_IDS[:3])).milestone,
            "ready_to_match",
        )
        self.assertEqual(vibe_progress(lines(*VIBE_AREA_IDS)).milestone, "deep")
        self.assertIsNone(vibe_progress(lines(*VIBE_AREA_IDS)).next_milestone)

    def test_lines_said_once_reach_first_impressions_only(self) -> None:
        progress = vibe_progress(lines(*VIBE_AREA_IDS, messages=1))

        self.assertEqual(progress.milestone, "first_impressions")
        self.assertEqual(progress.clear, ())
        self.assertEqual(progress.mentioned, VIBE_AREA_IDS)

    def test_old_text_only_lines_count_as_mentioned(self) -> None:
        progress = vibe_progress({area_id: "Old line." for area_id in BASIC_AREA_IDS})

        self.assertEqual(progress.milestone, "first_impressions")
        self.assertEqual(progress.known, BASIC_AREA_IDS)

    def test_many_deeper_areas_without_the_basics_are_not_ready(self) -> None:
        progress = vibe_progress(lines(*DEEPER_AREA_IDS))

        self.assertEqual(progress.milestone, "first_impressions")
        self.assertEqual(progress.next_milestone, "basics")

    def test_model_updates_need_real_user_messages_as_evidence(self) -> None:
        updates = validate_vibe_updates(
            {
                "humor": {"line": "  Loves   dry jokes.  ", "evidence": [1, 3, 3]},
                "values": {"line": "Thinks loyalty matters.", "evidence": [2]},  # a companion message
                "interests": {"line": "Likes F1."},  # no evidence
                "conflict": {"line": "x" * 400, "evidence": [5, 99]},
                "zodiac": {"line": "Leo", "evidence": [1]},
                "deal_breakers": "Hates flakes.",  # old shape
            },
            resolve_evidence=resolve_any,
        )

        self.assertEqual(updates["humor"]["text"], "Loves dry jokes.")
        self.assertEqual(
            updates["humor"]["evidence"],
            [{"conversation_id": "c1", "message_index": 1}, {"conversation_id": "c1", "message_index": 3}],
        )
        self.assertEqual(set(updates), {"humor", "conflict"})
        self.assertLessEqual(len(updates["conflict"]["text"]), 220)
        self.assertEqual(len(updates["conflict"]["evidence"]), 1)
        self.assertEqual(validate_vibe_updates("humor", resolve_evidence=resolve_any), {})

    def test_merge_replaces_the_text_and_keeps_adding_evidence(self) -> None:
        merged = merge_vibe(
            {"humor": line("Old.", 1), "values": line("Kept.", 2)},
            {"humor": {"text": "New.", "evidence": [{"conversation_id": "c2", "message_index": 4}]}},
        )

        self.assertEqual(merged["humor"]["text"], "New.")
        self.assertEqual(len(merged["humor"]["evidence"]), 2)
        self.assertEqual(line_strength(merged["humor"]), "clear")
        self.assertEqual(merged["values"]["text"], "Kept.")


class MatchingUnderstandingTest(unittest.TestCase):
    def test_empty_card_starts_with_every_area_open_basics_first(self) -> None:
        progress = calculate_matching_understanding({})

        self.assertEqual(progress.level, "starting")
        self.assertEqual(progress.breadth_percent, 0)
        self.assertEqual(set(progress.unexplored_dimensions), set(MATCHING_DIMENSIONS))
        self.assertEqual(progress.unexplored_dimensions[: len(BASIC_AREA_IDS)], BASIC_AREA_IDS)

    def test_prompt_states_the_goal_and_what_is_known(self) -> None:
        progress = calculate_matching_understanding(
            {"humor": line("Laughs at deadpan jokes."), "interests": line("Loves F1.", 1)}
        )
        prompt = matching_understanding_prompt(progress, now=NOW)

        self.assertIn("who this user would truly get along with as a friend", prompt)
        self.assertIn("not a checklist", prompt)
        self.assertIn("- humor: Laughs at deadpan jokes.", prompt)
        self.assertIn("- interests (said once): Loves F1.", prompt)
        self.assertIn("friend wish:", prompt)
        self.assertNotIn("New (", prompt)

    def test_new_milestone_is_news_for_a_day_only(self) -> None:
        areas = lines(*BASIC_AREA_IDS)
        fresh = calculate_matching_understanding(areas, milestone_reached_at=NOW - timedelta(hours=3))
        stale = calculate_matching_understanding(areas, milestone_reached_at=NOW - timedelta(days=2))

        self.assertIn("New (about 3 hours ago)", matching_understanding_prompt(fresh, now=NOW))
        self.assertIn("in your own words", matching_understanding_prompt(fresh, now=NOW))
        self.assertNotIn("New (", matching_understanding_prompt(stale, now=NOW))

    def test_listener_first_planner_receives_a_private_discovery_hint_when_open(self) -> None:
        progress = calculate_matching_understanding({**lines("humor"), **lines("values", messages=1)})

        plan = build_conversation_plan(
            user_text="I have a quiet evening today.",
            intent=ContextQueryIntent(),
            emotion_state=EmotionState(),
            conversational_stance=ConversationalStance(),
            matching_understanding=progress,
            listener_first=True,
        )

        self.assertTrue(plan.matching_discovery_allowed)
        # Said once comes first (worth hearing again), then open basics.
        self.assertEqual(plan.matching_discovery_topics[:2], ("values", "friend_wish"))
        self.assertNotIn("humor", plan.matching_discovery_topics)

    def test_listener_first_planner_defers_discovery_for_a_listening_boundary(self) -> None:
        plan = build_conversation_plan(
            user_text="Bas meri baat suno, questions mat puchna.",
            intent=ContextQueryIntent(),
            emotion_state=EmotionState(),
            conversational_stance=ConversationalStance(constraints=("listen_only", "no_questions")),
            matching_understanding=calculate_matching_understanding({}),
            listener_first=True,
        )

        self.assertFalse(plan.matching_discovery_allowed)
        self.assertEqual(plan.matching_discovery_topics, ())


class VibeCardStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()

    def test_milestone_time_moves_only_when_the_milestone_changes(self) -> None:
        first = update_vibe_card("vibe-user", lines("humor", "values"), now=NOW)
        later = update_vibe_card("vibe-user", {"humor": line("Rewritten.")}, now=NOW + timedelta(hours=5))

        self.assertEqual(first["milestone"], "first_impressions")
        self.assertEqual(later["milestone"], "first_impressions")
        self.assertEqual(
            get_vibe_card("vibe-user")["milestone_reached_at"].replace(tzinfo=timezone.utc),
            NOW,
        )
        self.assertEqual(get_vibe_card("vibe-user")["areas"]["humor"]["text"], "Rewritten.")

    def test_removing_a_line_can_drop_the_milestone(self) -> None:
        update_vibe_card("vibe-user", lines("humor", "values"), now=NOW)
        saved = update_vibe_card("vibe-user", {}, remove=("values",))

        self.assertEqual(set(saved["areas"]), {"humor"})
        self.assertEqual(saved["milestone"], "starting")

    def test_card_is_per_user(self) -> None:
        update_vibe_card("vibe-user", lines("humor"))

        self.assertEqual(get_vibe_card("other-user")["areas"], {})


class MatchingUnderstandingContextIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation(
            {"id": "matching-conversation", "status": "active", "messages": []},
            "matching-user",
        )

    def test_build_reads_the_stored_card(self) -> None:
        update_vibe_card("matching-user", lines("humor", "interests"))

        progress = build_matching_understanding(user_id="matching-user")

        self.assertEqual(progress.level, "first_impressions")
        self.assertEqual(progress.known_dimensions, ("humor", "interests"))

    def test_v3_1_adds_the_friend_vibe_section_without_changing_v3(self) -> None:
        update_vibe_card("matching-user", {"humor": line("Laughs at deadpan jokes.")})
        common = {
            "conversation_id": "matching-conversation",
            "user_text": "Today was exhausting, bas meri baat suno.",
            "user_id": "matching-user",
            "user_profile": {"user_id": "matching-user"},
            "model": "llama-70b",
            "agent_tone": "auto",
            "agent_name": "Omi",
            "style_source_id": None,
            "user_message_index": 0,
            "assistant_message_index": 1,
        }

        v3 = build_model_context_package(**common, prompt_version_id="v3")
        v3_1 = build_model_context_package(**common, prompt_version_id="v3-1")

        self.assertEqual(v3_1.snapshot["context"]["matching_understanding"]["level"], "starting")
        self.assertFalse(v3_1.snapshot["summary"]["matching_discovery_allowed"])
        self.assertNotIn("## Friend Vibe", v3.system_prompt)
        self.assertIn("## Friend Vibe", v3_1.system_prompt)
        self.assertIn("- humor: Laughs at deadpan jokes.", v3_1.system_prompt)
        self.assertIn("A correction replaces the earlier meaning exactly", v3_1.system_prompt)
        self.assertNotIn("matching_understanding", v3.snapshot["context"])


if __name__ == "__main__":
    unittest.main()
