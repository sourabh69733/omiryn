"""Date-aware recall: code works out when things happen, one-off and repeating."""

import asyncio
import unittest
from datetime import UTC, date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from agent.context_engine.prompt_engine.blocks import _SOURCE_BLOCKS, BLOCK_CHAR_LIMITS
from agent.context_engine.sources.calendar import calendar_sources
from agent.context_engine.sources.memories import memory_time_note
from agent.memory_engine.memories.dates import next_occurrence, normalize_repeats, occurrences_between, period_range
from agent.memory_engine.memories.retrieval import memories_on_dates, might_fit_memories
from agent.proactive.policy import due_event
from agent.tools import ToolCall, ToolContext, run_calls, tool_specs
from storage import create_agent_memory, reset_db, save_conversation, set_user_timezone

USER_ID = "dates-user"
ZONE = ZoneInfo("Asia/Kolkata")
# A Wednesday.
NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
TODAY = date(2026, 11, 4)


def _memory(statement: str, **fields) -> dict:
    source = f"src-{statement[:12]}"
    save_conversation({"id": source, "status": "completed", "messages": [{"role": "user", "content": statement}]}, USER_ID)
    return create_agent_memory(
        {
            "user_id": USER_ID,
            "kind": "episodic",
            "purposes": ["personalization"],
            "key": statement[:20],
            "value": statement,
            "statement": statement,
            "confidence": 0.9,
            "importance": 0.5,
            "created_at": "2026-10-01T10:00:00+00:00",
            "evidence": [{"conversation_id": source, "message_index": 0, "exact_quote": statement, "observed_at": "2026-10-01T10:00:00+00:00"}],
            **fields,
        }
    )


class RepeatsValueTest(unittest.TestCase):
    def test_keeps_what_code_can_compute_and_drops_the_rest(self) -> None:
        self.assertEqual(normalize_repeats("yearly:03-12"), "yearly:03-12")
        self.assertEqual(normalize_repeats("yearly:02-29"), "yearly:02-29")
        self.assertEqual(normalize_repeats("monthly:5"), "monthly:5")
        self.assertEqual(normalize_repeats("Weekly:Thu, tue"), "weekly:tue,thu")
        for bad in ("yearly", "yearly:13-40", "monthly", "monthly:32", "monthly:0", "weekly", "weekly:someday", "daily", True, None):
            self.assertIsNone(normalize_repeats(bad), bad)

    def test_every_day_of_the_week_is_a_habit_not_a_calendar_entry(self) -> None:
        self.assertIsNone(normalize_repeats("weekly:mon,tue,wed,thu,fri,sat,sun"))


class OccurrencesTest(unittest.TestCase):
    def test_one_off_only_on_its_day(self) -> None:
        memory = {"occurred_at": "2026-11-06T06:30:00+00:00"}
        self.assertEqual(occurrences_between(memory, TODAY, date(2026, 11, 10), ZONE), [date(2026, 11, 6)])
        self.assertEqual(occurrences_between(memory, date(2026, 12, 1), date(2026, 12, 9), ZONE), [])

    def test_the_day_is_the_users_not_utc(self) -> None:
        memory = {"occurred_at": "2026-11-06T20:00:00+00:00"}
        self.assertEqual(occurrences_between(memory, TODAY, date(2026, 11, 10), ZONE), [date(2026, 11, 7)])

    def test_birthday_comes_back_every_year_also_before_it_was_told(self) -> None:
        memory = {"repeats": "yearly:03-12", "created_at": "2026-10-01T10:00:00+00:00"}
        self.assertEqual(next_occurrence(memory, TODAY, ZONE), date(2027, 3, 12))
        self.assertEqual(occurrences_between(memory, date(2025, 3, 1), date(2025, 3, 31), ZONE), [date(2025, 3, 12)])

    def test_feb_29_falls_on_feb_28_in_a_short_year(self) -> None:
        self.assertEqual(next_occurrence({"repeats": "yearly:02-29"}, TODAY, ZONE), date(2027, 2, 28))

    def test_monthly_on_the_31st_uses_the_last_day(self) -> None:
        self.assertEqual(next_occurrence({"repeats": "monthly:31"}, TODAY, ZONE), date(2026, 11, 30))

    def test_a_date_beside_a_repeat_is_ignored(self) -> None:
        memory = {"repeats": "monthly:5", "occurred_at": "2026-11-04T06:30:00+00:00"}
        self.assertEqual(next_occurrence(memory, TODAY, ZONE), date(2026, 11, 5))

    def test_weekly_days(self) -> None:
        memory = {"repeats": "weekly:tue,thu", "created_at": "2026-10-01T10:00:00+00:00"}
        self.assertEqual(
            occurrences_between(memory, TODAY, date(2026, 11, 12), ZONE),
            [date(2026, 11, 5), date(2026, 11, 10), date(2026, 11, 12)],
        )

    def test_weekly_is_not_claimed_before_it_was_known_or_after_it_ended(self) -> None:
        memory = {"repeats": "weekly:tue", "created_at": "2026-10-01T10:00:00+00:00", "valid_until": "2026-11-05T06:30:00+00:00"}
        self.assertEqual(occurrences_between(memory, date(2026, 1, 1), date(2026, 1, 31), ZONE), [])
        self.assertIsNone(next_occurrence({**memory, "valid_until": "2026-11-03T00:00:00+00:00"}, TODAY, ZONE))


class PeriodTest(unittest.TestCase):
    def test_periods(self) -> None:
        self.assertEqual(period_range("this_week", TODAY), (date(2026, 11, 2), date(2026, 11, 8)))
        self.assertEqual(period_range("last_week", TODAY), (date(2026, 10, 26), date(2026, 11, 1)))
        self.assertEqual(period_range("next_week", TODAY), (date(2026, 11, 9), date(2026, 11, 15)))
        self.assertEqual(period_range("last_month", TODAY), (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(period_range("next_month", TODAY), (date(2026, 12, 1), date(2026, 12, 31)))
        self.assertEqual(period_range("next_month", date(2026, 12, 20)), (date(2027, 1, 1), date(2027, 1, 31)))
        self.assertIsNone(period_range("someday", TODAY))


class StoredDatesTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        set_user_timezone(USER_ID, "Asia/Kolkata")

    def test_repeats_is_saved_and_read_back(self) -> None:
        memory = _memory("Goes to the gym.", kind="semantic", repeats="weekly:tue,thu")
        self.assertEqual(memory["repeats"], "weekly:tue,thu")

    def test_private_and_replaced_memories_stay_out(self) -> None:
        _memory("Has a scan.", occurred_at="2026-11-06T06:30:00+00:00", sensitivity="highly_sensitive")
        _memory("Prefers mornings.", occurred_at="2026-11-06T06:30:00+00:00", kind="procedural")
        kept = _memory("Has an interview.", occurred_at="2026-11-06T06:30:00+00:00")
        found = memories_on_dates(USER_ID, TODAY, date(2026, 11, 10), ZONE, limit=8)
        self.assertEqual([memory["id"] for _, memory in found], [kept["id"]])

    def test_a_plan_past_its_end_date_still_happened(self) -> None:
        kept = _memory("Was in Goa.", occurred_at="2026-10-20T06:30:00+00:00", valid_until="2026-10-25T06:30:00+00:00")
        found = memories_on_dates(USER_ID, date(2026, 10, 1), date(2026, 10, 31), ZONE, limit=8)
        self.assertEqual([memory["id"] for _, memory in found], [kept["id"]])

    def test_calendar_lists_coming_dates_soonest_first(self) -> None:
        _memory("Has an interview.", occurred_at="2026-11-06T11:30:00+00:00")
        _memory("Goes to the gym.", kind="semantic", repeats="weekly:thu")
        _memory("Sister's birthday is on 8 November.", kind="relationship", repeats="yearly:11-08")
        _memory("Went to Goa.", occurred_at="2026-10-20T06:30:00+00:00")
        _memory("Dad's birthday is on 1 February.", repeats="yearly:02-01")
        source = calendar_sources(USER_ID, NOW)[0]
        lines = source["content"].splitlines()[1:]
        self.assertEqual(len(lines), 3)
        self.assertIn("Thu 5 Nov 2026 (tomorrow), every Thu: Goes to the gym.", lines[0])
        self.assertIn("Fri 6 Nov 2026 (this Friday, in 2 days), 5:00 pm: Has an interview.", lines[1])
        self.assertIn("Sun 8 Nov 2026 (this Sunday, in 4 days), every year: Sister's birthday", lines[2])
        self.assertEqual(_SOURCE_BLOCKS[source["source_type"]], "calendar")
        self.assertLessEqual(len(source["content"]), BLOCK_CHAR_LIMITS["calendar"])

    def test_calendar_holds_recent_one_off_events_oldest_first(self) -> None:
        _memory("Went to Jaipur.", occurred_at="2026-10-28T06:30:00+00:00")
        _memory("Saw a concert.", occurred_at="2026-11-01T06:30:00+00:00")
        _memory("Went to Goa.", occurred_at="2026-09-01T06:30:00+00:00")
        _memory("Goes to the gym.", kind="semantic", repeats="weekly:mon")
        lines = calendar_sources(USER_ID, NOW)[0]["content"].splitlines()[1:]
        self.assertEqual(len(lines), 3)
        self.assertIn("Wed 28 Oct 2026 (on Wednesday, 7 days ago)"[:15], lines[0])
        self.assertIn("Went to Jaipur.", lines[0])
        self.assertIn("Saw a concert.", lines[1])
        # The gym shows its next time only, never a past Monday.
        self.assertIn("Mon 9 Nov 2026", lines[2])

    def test_calendar_says_when_it_left_dates_out(self) -> None:
        for day in range(1, 13):
            _memory(f"Plan number {day:02d}.", occurred_at=f"2026-11-{day + 4:02d}T06:30:00+00:00")
        content = calendar_sources(USER_ID, NOW)[0]["content"]
        lines = content.splitlines()
        self.assertEqual(len(lines), 12)
        self.assertIn("memories_by_date has the rest", lines[-1])
        self.assertLessEqual(len(content), BLOCK_CHAR_LIMITS["calendar"])

    def test_no_dates_no_calendar(self) -> None:
        _memory("Loves old films.", kind="semantic")
        self.assertEqual(calendar_sources(USER_ID, NOW), [])

    def test_time_note_gives_the_next_date_not_the_anchor(self) -> None:
        memory = {"repeats": "yearly:03-12", "occurred_at": "2024-03-12T06:30:00+00:00"}
        note = memory_time_note(memory, ZONE, NOW)
        self.assertIn("every year, next Fri 12 Mar 2027", note)
        self.assertNotIn("2024", note)
        self.assertNotIn("happened", note)

    def test_might_fit_lifts_a_birthday_near_but_not_a_weekly_habit(self) -> None:
        birthday = _memory("Sister's birthday is on 8 November.", kind="relationship", repeats="yearly:11-08", importance=0.3)
        gym = _memory("Goes to the gym.", kind="semantic", repeats="weekly:thu", importance=0.3)
        films = _memory("Loves old films.", kind="semantic", importance=0.8)
        ranked = [memory["id"] for memory in might_fit_memories(USER_ID, exclude_ids=set(), recently_offered=set(), now=NOW)]
        self.assertEqual(ranked, [birthday["id"], films["id"], gym["id"]])

    def test_a_repeating_thing_gets_no_how_did_it_go(self) -> None:
        told = "2026-10-01T10:00:00+00:00"
        memory = {"occurred_at": "2026-11-03T06:30:00+00:00", "created_at": told, "status": "active", "allowed_uses": ["reply_context"], "sensitivity": "standard"}
        self.assertIsNotNone(due_event([memory], NOW, ZONE))
        self.assertIsNone(due_event([{**memory, "repeats": "weekly:tue"}], NOW, ZONE))


class MemoriesByDateToolTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        set_user_timezone(USER_ID, "Asia/Kolkata")
        self.context = ToolContext(user_id=USER_ID, conversation_id="chat")

    def _call(self, **arguments) -> str:
        with patch("agent.tools.memory_dates.utc_now", return_value=NOW):
            results = asyncio.run(run_calls([ToolCall("memories_by_date", arguments)], self.context))
        return results[0].note

    def test_on_for_a_signed_in_user(self) -> None:
        names = [spec["function"]["name"] for spec in tool_specs(self.context)]
        self.assertIn("memories_by_date", names)
        self.assertNotIn("memories_by_date", [spec["function"]["name"] for spec in tool_specs(ToolContext(user_id=None))])

    def test_named_period(self) -> None:
        _memory("Went to Jaipur.", occurred_at="2026-10-28T06:30:00+00:00")
        note = self._call(period="last_week")
        self.assertIn("Mon 26 Oct 2026 to Sun 1 Nov 2026", note)
        self.assertIn("Went to Jaipur.", note)

    def test_own_dates_in_either_order(self) -> None:
        _memory("Went to Goa.", occurred_at="2026-03-15T06:30:00+00:00")
        self.assertIn("Went to Goa.", self._call(start_date="2026-03-31", end_date="2026-03-01"))

    def test_nothing_found_says_so(self) -> None:
        self.assertIn("Nothing dated", self._call(period="today"))

    def test_bad_input_gets_a_note_not_an_error(self) -> None:
        self.assertIn("Give a period", self._call(period="someday"))
        self.assertIn("Give a period", self._call(start_date="soon"))


if __name__ == "__main__":
    unittest.main()
