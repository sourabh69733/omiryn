import os
import unittest
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.context_engine.engine import build_model_context_package
from agent.context_engine.prompt_engine.modules.behavior import time_awareness_prompt
from agent.providers import _provider_messages
from agent.providers.shared.messages import reply_window
from agent.shared.clock import frozen_time, utc_now
from agent.shared.timeline import (
    conversation_time,
    day_part,
    day_notes,
    humanize_gap,
    relative_day,
    valid_timezone_name,
)
from api.main import app, current_user
from api.routes.public import _reset_public_rate_limits
from security.auth import CurrentUser
from storage import get_conversation, get_user_timezone, reset_db, save_conversation

NOW = datetime(2026, 9, 22, 15, 44, tzinfo=UTC)  # 9:14 pm in Asia/Kolkata


def _message(role: str, content: str, at: datetime) -> dict:
    return {"role": role, "content": content, "created_at": at.isoformat()}


class ClockTest(unittest.TestCase):
    def test_frozen_time_pins_and_restores_now(self) -> None:
        with frozen_time(NOW):
            self.assertEqual(utc_now(), NOW)
        self.assertNotEqual(utc_now(), NOW)

    def test_frozen_time_rejects_naive_datetime(self) -> None:
        with self.assertRaises(ValueError):
            with frozen_time(datetime(2026, 9, 22)):
                pass


class TimelineTest(unittest.TestCase):
    def test_humanize_gap_uses_the_largest_whole_unit(self) -> None:
        self.assertEqual(humanize_gap(timedelta(seconds=20)), "less than a minute")
        self.assertEqual(humanize_gap(timedelta(minutes=1)), "1 minute")
        self.assertEqual(humanize_gap(timedelta(hours=5, minutes=50)), "5 hours")
        self.assertEqual(humanize_gap(timedelta(days=2, hours=3)), "2 days")
        self.assertEqual(humanize_gap(timedelta(days=15)), "2 weeks")
        self.assertEqual(humanize_gap(timedelta(days=400)), "1 year")

    def test_day_part(self) -> None:
        self.assertEqual(day_part(datetime(2026, 9, 22, 9)), "morning")
        self.assertEqual(day_part(datetime(2026, 9, 22, 14)), "afternoon")
        self.assertEqual(day_part(datetime(2026, 9, 22, 19)), "evening")
        self.assertEqual(day_part(datetime(2026, 9, 22, 23)), "night")
        self.assertEqual(day_part(datetime(2026, 9, 22, 3)), "late night")

    def test_valid_timezone_name_rejects_unknown_values(self) -> None:
        self.assertEqual(valid_timezone_name(" Europe/Berlin "), "Europe/Berlin")
        self.assertIsNone(valid_timezone_name("Mars/Olympus"))
        self.assertIsNone(valid_timezone_name("../../etc/passwd"))
        self.assertIsNone(valid_timezone_name(None))

    def test_conversation_time_reports_gap_in_user_timezone(self) -> None:
        messages = [
            _message("user", "hi", NOW - timedelta(days=2, hours=1)),
            _message("assistant", "hey!", NOW - timedelta(days=2)),
        ]
        timing = conversation_time(messages, "Asia/Kolkata", NOW)
        fields = timing.profile_fields()

        self.assertTrue(timing.new_session)
        self.assertEqual(fields["last_user_message_ago"], "2 days")
        self.assertEqual(fields["current_local_label"], "Tuesday 22 Sep 2026, 9:14 pm")
        self.assertEqual(fields["current_day_part"], "night")
        self.assertEqual(fields["timezone"], "Asia/Kolkata")

    def test_conversation_time_ignores_assistant_only_activity(self) -> None:
        messages = [_message("assistant", "welcome", NOW - timedelta(minutes=5))]
        timing = conversation_time(messages, "Asia/Kolkata", NOW)

        self.assertIsNone(timing.gap_since_last_user_message)
        self.assertFalse(timing.new_session)
        self.assertNotIn("last_user_message_ago", timing.profile_fields())

    def test_conversation_time_falls_back_for_invalid_timezone(self) -> None:
        with patch.dict(os.environ, {"AGENT_DEFAULT_TIMEZONE": "Europe/London"}):
            timing = conversation_time([], "Not/AZone", NOW)
        self.assertEqual(timing.timezone, "Europe/London")

    def test_short_pause_is_not_a_new_session(self) -> None:
        messages = [_message("user", "brb", NOW - timedelta(hours=2))]
        self.assertFalse(conversation_time(messages, "UTC", NOW).new_session)

    def test_session_gap_is_configurable(self) -> None:
        messages = [_message("user", "brb", NOW - timedelta(hours=2))]
        with patch.dict(os.environ, {"AGENT_SESSION_GAP_HOURS": "1"}):
            self.assertTrue(conversation_time(messages, "UTC", NOW).new_session)


class RelativeDayTest(unittest.TestCase):
    def test_relative_day_wording(self) -> None:
        today = date(2026, 9, 16)
        cases = {
            date(2026, 9, 16): "today",
            date(2026, 9, 17): "tomorrow",
            date(2026, 9, 15): "yesterday",
            date(2026, 9, 18): "this Friday, in 2 days",
            date(2026, 9, 13): "on Sunday, 3 days ago",
            date(2026, 9, 25): "in 9 days",
            date(2026, 10, 7): "in 3 weeks",
            date(2026, 6, 1): "3 months ago",
        }
        for day, expected in cases.items():
            with self.subTest(day=day):
                self.assertEqual(relative_day(day, today), expected)


class DayNotesTest(unittest.TestCase):
    def test_first_user_message_gets_its_day_and_later_ones_only_on_change(self) -> None:
        monday = datetime(2026, 9, 14, 14, 30, tzinfo=UTC)  # 8 pm IST
        messages = [
            _message("assistant", "hey!", monday),
            _message("user", "long day", monday),
            _message("user", "interview next Friday", monday + timedelta(minutes=3)),
            _message("user", "still up", monday + timedelta(hours=4)),  # past midnight IST
            _message("assistant", "go sleep!", monday + timedelta(hours=4)),
            _message("user", "hey, back", monday + timedelta(days=2)),
            {"role": "user", "content": "no time"},
        ]
        notes = day_notes(messages, "Asia/Kolkata")

        self.assertEqual(
            notes,
            [
                None,
                "(Mon 14 Sep, 8:00 pm)",
                None,
                "(Tue 15 Sep, 12:00 am)",
                None,
                "(Wed 16 Sep, 8:00 pm, 1 day later)",
                None,
            ],
        )

    def test_provider_messages_prefix_user_turns_but_never_assistant_turns(self) -> None:
        messages = [
            _message("user", "going to sleep", NOW - timedelta(days=4)),
            _message("assistant", "good night", NOW - timedelta(days=4)),
            _message("assistant", "morning! how was it?", NOW - timedelta(days=1)),
            _message("user", "I'm back", NOW),
        ]
        provider = _provider_messages(messages)

        self.assertTrue(provider[0]["content"].startswith("(Fri 18 Sep, "))
        self.assertRegex(provider[-1]["content"], r"^\(Tue 22 Sep, [0-9:]+ [ap]m, 1 day later\) I'm back$")
        self.assertTrue(all(m["content"][0] != "(" for m in provider if m["role"] == "assistant"))
        self.assertEqual(messages[-1]["content"], "I'm back")

    def test_reply_window_notes_use_the_user_timezone(self) -> None:
        late_utc = datetime(2026, 9, 21, 20, 0, tzinfo=UTC)  # Tue 22 Sep, 1:30 am in IST
        window = reply_window([_message("user", "can't sleep", late_utc)], None, "Asia/Kolkata")
        self.assertEqual(_provider_messages(window)[0]["content"], "(Tue 22 Sep, 1:30 am) can't sleep")

    def test_an_hour_long_pause_inside_a_session_gets_a_time_note(self) -> None:
        start = datetime(2026, 9, 26, 11, 43, tzinfo=UTC)  # 5:13 pm IST
        messages = [
            _message("user", "tell me a story", start),
            _message("user", "why so long", start + timedelta(minutes=50)),
            _message("user", "hi, what is next now?", start + timedelta(hours=2, minutes=21)),
        ]
        self.assertEqual(
            day_notes(messages, "Asia/Kolkata"),
            ["(Sat 26 Sep, 5:13 pm)", None, "(7:34 pm, 1 hour later)"],
        )


class TimeAwarenessPromptTest(unittest.TestCase):
    def test_prompt_mentions_break_for_new_session(self) -> None:
        profile = conversation_time(
            [_message("user", "bye", NOW - timedelta(days=2))], "Asia/Kolkata", NOW
        ).profile_fields()
        prompt = time_awareness_prompt(profile)

        self.assertIn("Tuesday 22 Sep 2026, 9:14 pm (night)", prompt)
        self.assertIn("2 days ago", prompt)
        self.assertIn("back after a break", prompt)

    def test_prompt_for_first_message_and_unknown_time(self) -> None:
        first = time_awareness_prompt(conversation_time([], "UTC", NOW).profile_fields())
        self.assertIn("first message in this chat", first)
        self.assertNotIn("back after a break", first)
        self.assertIn("unknown", time_awareness_prompt({}))


class TimeAwarenessApiTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["AUTH_REQUIRED"] = "false"
        os.environ["AGENT_PROVIDER"] = "mock"
        os.environ["AGENT_PIPELINE_VERSION"] = "v1"
        os.environ["AGENT_ROLLOUT"] = "off"
        app.dependency_overrides.clear()

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id="time-user", email="time@example.com", display_name="Time User")

        app.dependency_overrides[current_user] = signed_in_user
        _reset_public_rate_limits()
        reset_db()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        os.environ.pop("AGENT_PIPELINE_VERSION", None)
        os.environ.pop("AGENT_ROLLOUT", None)
        app.dependency_overrides.clear()

    def test_browser_timezone_is_stored_and_invalid_values_are_ignored(self) -> None:
        response = self.client.post(
            "/api/agent/conversations", headers={"X-Timezone": "America/New_York"}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(get_user_timezone("time-user"), "America/New_York")

        conversation_id = response.json()["id"]
        self.client.post(
            f"/api/agent/conversations/{conversation_id}/messages",
            json={"message": "I just got back from a long walk by the river"},
            headers={"X-Timezone": "Not/AZone"},
        )
        self.assertEqual(get_user_timezone("time-user"), "America/New_York")

    def test_user_message_is_stamped_with_arrival_time(self) -> None:
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]
        with frozen_time(NOW):
            self.client.post(
                f"/api/agent/conversations/{conversation_id}/messages",
                json={"message": "I just got back from a long walk by the river"},
            )
        messages = get_conversation(conversation_id, "time-user")["messages"]
        user_message = next(m for m in messages if m["role"] == "user")
        self.assertEqual(user_message["created_at"], NOW.isoformat())

    def test_context_package_tells_the_model_how_long_the_user_was_away(self) -> None:
        conversation_id = self.client.post(
            "/api/agent/conversations", headers={"X-Timezone": "Asia/Kolkata"}
        ).json()["id"]
        conversation = get_conversation(conversation_id, "time-user")
        conversation["messages"] = [
            *conversation["messages"],
            _message("user", "talk tomorrow", NOW - timedelta(days=3)),
            _message("assistant", "sure, good night", NOW - timedelta(days=3)),
        ]
        save_conversation(conversation, "time-user")

        with frozen_time(NOW):
            package = build_model_context_package(
                conversation_id=conversation_id,
                user_text="hey, I'm back",
                user_id="time-user",
                user_profile={},
                model=None,
                agent_tone="auto",
                agent_name=None,
                style_source_id=None,
                user_message_index=len(conversation["messages"]),
                assistant_message_index=len(conversation["messages"]) + 1,
            )

        self.assertIn("Tuesday 22 Sep 2026, 9:14 pm", package.system_prompt)
        self.assertIn("3 days ago", package.system_prompt)
        self.assertIn("back after a break", package.system_prompt)


if __name__ == "__main__":
    unittest.main()
