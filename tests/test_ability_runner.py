"""The ability runner's marking, ordering and report, with no model or search calls."""

import json
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from agent.evals.abilities.questions import QUESTIONS
from agent.evals.abilities.report import as_markdown, tally
from agent.evals.abilities.runner import Asked, Mark, ToolUse, chains, chat_before, code_mark, final_mark, judge_input, message_text, parse_judgment, run

BY_ID = {question.id: question for question in QUESTIONS}
SEARCHED = (ToolUse("web_search", {"query": "GATE 2027 form date"}, "The form opened on 2 September 2026."),)


class CodeMarkTest(unittest.TestCase):
    def test_no_reply_and_no_look_up_are_decided_in_code(self) -> None:
        gate = BY_ID["exams-gate-form"]
        self.assertEqual(code_mark(Asked(gate, error="TimeoutError")).reason, "no_reply")
        self.assertEqual(code_mark(Asked(gate, "form abhi open hoga")).reason, "did_not_search")
        self.assertIsNone(code_mark(Asked(gate, "2 September ko khula tha, ab band hai", SEARCHED)))
        # The places tool counts as looking it up.
        self.assertIsNone(code_mark(Asked(BY_ID["career-f-drives"], "x", (ToolUse("find_places", {}, ""),))))

    def test_a_right_answer_that_searched_for_no_reason_is_only_partly_right(self) -> None:
        emi = BY_ID["money-emi"]
        right = Mark("right", "ok", "Gave 4,167.", "judge")
        self.assertEqual(final_mark(Asked(emi, "4,167 per month", SEARCHED), right).reason, "searched_needlessly")
        self.assertEqual(final_mark(Asked(emi, "4,167 per month"), right), right)

    def test_not_looking_up_stays_wrong_and_keeps_what_the_judge_read(self) -> None:
        mark = final_mark(Asked(BY_ID["exams-gate-form"], "next month"), Mark("wrong", "made_up", "Gave a date with no source.", "judge"))
        self.assertEqual((mark.verdict, mark.reason, mark.by), ("wrong", "did_not_search", "code"))
        self.assertIn("Gave a date with no source.", mark.note)

    def test_with_no_judge_a_reply_is_left_for_a_person(self) -> None:
        self.assertEqual(final_mark(Asked(BY_ID["money-emi"], "4,167"), None).reason, "not_run")


class JudgeTest(unittest.TestCase):
    def test_the_judge_reads_the_rule_the_date_and_what_the_tools_returned(self) -> None:
        asked = Asked(BY_ID["exams-days-left"], "17 din", SEARCHED)
        sent = json.loads(judge_input(asked, today=datetime(2026, 11, 20, 6, 0, tzinfo=UTC)))
        self.assertEqual(sent["today"], "Friday, 20 November 2026, 11:30 India time")
        self.assertEqual(sent["said_earlier"], "My semester exams start on 7 December.")
        self.assertIn("counts the days", sent["rule_a_right_reply"])
        self.assertEqual(sent["tools_called"][0]["returned"], "The form opened on 2 September 2026.")

    def test_only_a_well_formed_judgment_is_taken(self) -> None:
        self.assertEqual(parse_judgment({"verdict": "Wrong", "reason": "made_up", "note": " a  date "}), Mark("wrong", "made_up", "a date", "judge"))
        self.assertEqual(parse_judgment({"verdict": "right", "reason": "ok"}).verdict, "right")
        # A reply the judge calls right while its own list shows a missing part is only partly right.
        soft = parse_judgment({"parts": [{"part": "uses plants", "met": True}, {"part": "notes the date is close", "met": False}], "verdict": "right", "reason": "ok", "note": "Good ideas."})
        self.assertEqual((soft.verdict, soft.reason), ("partly", "missed_the_ask"))
        self.assertIn("notes the date is close", soft.note)
        # Seen from the real judge: "partly" with "ok". The verdict wins.
        self.assertEqual(parse_judgment({"verdict": "partly", "reason": "ok", "note": "No date."}), Mark("partly", "missed_the_ask", "No date.", "judge"))
        self.assertEqual(parse_judgment({"verdict": "right", "reason": "made_up"}).verdict, "partly")
        for bad in ({"verdict": "fine", "reason": "ok"}, {"verdict": "wrong", "reason": "did_not_search"}, {"verdict": "wrong", "reason": "who knows"}, {}):
            self.assertIsNone(parse_judgment(bad), bad)


class RunTest(unittest.IsolatedAsyncioTestCase):
    def test_what_was_said_earlier_and_pasted_text_reach_the_chat(self) -> None:
        before = chat_before(BY_ID["you-gift"])
        self.assertEqual([message["role"] for message in before], ["user", "assistant"])
        self.assertIn("2 December", before[0]["content"])
        self.assertEqual(chat_before(BY_ID["money-emi"]), [])
        self.assertIn("Notice for all hostel residents", message_text(BY_ID["write-summary"]))

    def test_a_follow_up_brings_the_question_it_follows(self) -> None:
        self.assertEqual([[q.id for q in group] for group in chains([BY_ID["exams-cat-date"]])], [["exams-cat-admit", "exams-cat-date"]])
        self.assertEqual(len(chains(list(QUESTIONS))), sum(1 for question in QUESTIONS if not question.after))

    async def test_a_run_asks_follow_ups_in_the_same_chat_and_skips_what_it_cannot_send(self) -> None:
        asked_with: dict[str, str | None] = {}

        async def fake_ask(user_id, question, *, model, before=None):
            asked_with[question.id] = before.question.id if before else None
            return Asked(question, "ok reply", SEARCHED if question.search else ())

        picked = [BY_ID[name] for name in ("exams-cat-date", "handed-photo", "money-emi")]
        with patch("storage.set_user_timezone"):
            results = await run(picked, model="claude-haiku-5-5", use_judge=False, ask_one=fake_ask)
        self.assertEqual([asked.question.id for asked, _ in results], ["exams-cat-date", "money-emi", "handed-photo"])
        self.assertEqual(asked_with, {"exams-cat-admit": None, "exams-cat-date": "exams-cat-admit", "money-emi": None})
        self.assertEqual(tally(results)["not_run"], 1)


class ReportTest(unittest.TestCase):
    def test_the_report_gives_the_score_the_reasons_and_every_reply(self) -> None:
        results = [
            (Asked(BY_ID["career-s-internship-open"], "Google STEP 30 Nov tak open hai", SEARCHED, 6.2), Mark("right", "ok", "Named an open programme with its date.", "judge")),
            (Asked(BY_ID["exams-gate-form"], "next month aayega"), Mark("wrong", "did_not_search", "Answered without looking it up.")),
        ]
        page = as_markdown(results, reply_model="claude-sonnet-5-5", judge_model="judge-x", when="21 November 2026", cost_usd=0.12)
        self.assertIn("**1 right, 0 partly, 1 wrong** out of 2 asked. Cost of this run: $0.12.", page)
        self.assertIn("| In college, first to third year (about 18 to 21) | 1 | 0 | 0 | 1 |", page)
        self.assertIn("| Did not look it up | 1 |", page)
        self.assertIn("web_search(query='GATE 2027 form date') gave 36 letters", page)
        self.assertIn("- Omi: next month aayega", page)


if __name__ == "__main__":
    unittest.main()
