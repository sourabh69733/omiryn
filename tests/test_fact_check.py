"""The fact check: a reply that does not match what was looked up gets one rewrite; the rest pass untouched."""

import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from agent.context_engine.policy.facts import FactProblem, fact_check_input, fact_problems, fact_rewrite_instruction, looked_up_evidence
from agent.runtime.steps.checks import check_facts
from agent.runtime.steps.job import ReplyJob

ON = {"AGENT_FACT_CHECK": "true"}
PAGE = "You searched the web. [EPFO rules] Full PF withdrawal is allowed after 12 months of continuous unemployment. Form 19 is for final settlement."
REPLY = "EPFO portal par claim karo.<next_message>Agar 2 mahine tak nayi job nahi li, toh full settlement ke liye Form 19 bhar sakte ho."
SEARCHED = [
    {"role": "user", "content": "pf kaise nikalte hain"},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1_1", "name": "web_search", "arguments": "{}"}]},
    {"role": "tool", "tool_call_id": "call_1_1", "name": "web_search", "content": PAGE},
]
FOUND = {"conflicts": [{"reply_says": "Agar 2 mahine tak nayi job nahi li", "found": "after 12 months of continuous unemployment"}], "unsupported": []}


def job(generate, messages=None) -> ReplyJob:
    return ReplyJob(list(SEARCHED if messages is None else messages), {}, generate, user_id=None, conversation_id="c1", user_text="pf kaise nikalte hain")


class FactProblemsTest(unittest.TestCase):
    def test_only_what_the_look_up_tools_returned_is_evidence(self) -> None:
        messages = [*SEARCHED, {"role": "tool", "name": "search_chats", "content": "a line from their chat"}, {"role": "tool", "name": "read_page", "content": "page text"}]
        self.assertEqual(looked_up_evidence(messages), [PAGE, "page text"])
        self.assertEqual(looked_up_evidence([{"role": "user", "content": "hi"}]), [])

    def test_a_finding_is_kept_only_when_both_quotes_are_real(self) -> None:
        self.assertEqual(fact_problems(FOUND, REPLY, [PAGE]), [FactProblem("conflict", "Agar 2 mahine tak nayi job nahi li", "after 12 months of continuous unemployment")])
        not_said = {"conflicts": [{"reply_says": "3 mahine baad milta hai", "found": "after 12 months of continuous unemployment"}]}
        not_found = {"conflicts": [{"reply_says": "Agar 2 mahine tak nayi job nahi li", "found": "allowed after 6 months"}]}
        self.assertEqual(fact_problems(not_said, REPLY, [PAGE]), [])
        self.assertEqual(fact_problems(not_found, REPLY, [PAGE]), [])
        for broken in (None, "yes", {}, {"conflicts": ["x"]}, {"conflicts": [{"found": "12 months"}]}):
            self.assertEqual(fact_problems(broken, REPLY, [PAGE]), [])

    def test_the_same_figures_in_other_words_are_not_a_conflict(self) -> None:
        page = "The exam will be conducted on 24th November 2026."
        reply = "Kal hai, 24 November ko."
        agree = {"conflicts": [{"reply_says": "Kal hai, 24 November ko", "found": "The exam will be conducted on 24th November 2026"}]}
        self.assertEqual(fact_problems(agree, reply, [page]), [])

    def test_our_own_lines_to_the_model_are_not_evidence(self) -> None:
        search = 'Today is Monday, 23 November 2026. A date before today has passed. You searched the web for "x". Answer from these extracts.\n[ITR dates · https://x]\n  The due date was 31 July 2026.'
        page = "You read the page \"GATE\" at https://x. Below is the start of its text.\n---\nGATE is an exam."
        evidence = looked_up_evidence([{"role": "tool", "name": "web_search", "content": search}, {"role": "tool", "name": "read_page", "content": page}])
        self.assertEqual(evidence, ["[ITR dates · https://x]\n  The due date was 31 July 2026.", "GATE is an exam."])

    def test_unsupported_is_dropped_when_the_results_do_say_it(self) -> None:
        said_in_results = {"unsupported": [{"reply_says": "Form 19"}]}
        not_in_results = {"unsupported": [{"reply_says": "EPFO portal par claim karo"}]}
        self.assertEqual(fact_problems(said_in_results, REPLY, [PAGE]), [])
        self.assertEqual([problem.kind for problem in fact_problems(not_in_results, REPLY, [PAGE])], ["unsupported"])

    def test_the_rewrite_note_says_what_to_fix_and_to_keep_the_rest(self) -> None:
        note = fact_rewrite_instruction(REPLY, [FactProblem("conflict", "2 mahine", "12 months"), FactProblem("unsupported", "fees 500 hai")])
        self.assertIn('you wrote "2 mahine", but what you looked up says "12 months"', note)
        self.assertIn('you wrote "fees 500 hai" as a fact, and nothing you looked up says that', note)
        self.assertIn("Keep everything else as it was", note)

    def test_the_checker_reads_the_date_the_question_the_results_and_the_reply(self) -> None:
        read = json.loads(fact_check_input("r", "q", ["e"], today="Monday, 23 November 2026"))
        self.assertEqual(read, {"today": "Monday, 23 November 2026", "question": "q", "results": ["e"], "reply": "r"})


class FactCheckStepTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_reply_that_contradicts_the_page_is_rewritten_once_with_the_page_in_view(self) -> None:
        seen = []

        async def generate(messages, **kwargs):
            seen.append(messages)
            return "12 mahine tak job na ho toh full settlement milta hai, Form 19 se."

        with patch.dict(os.environ, ON), patch("agent.runtime.steps.checks.check_reply_facts", AsyncMock(return_value=FOUND)):
            fixed, info = await check_facts(REPLY, job(generate))

        self.assertEqual(fixed, "12 mahine tak job na ho toh full settlement milta hai, Form 19 se.")
        self.assertEqual(info, {"checked": True, "conflicts": 1, "unsupported": 0, "rewritten": True})
        self.assertEqual([message["role"] for message in seen[0]], ["user", "assistant", "tool", "system"])
        self.assertIn('what you looked up says "after 12 months of continuous unemployment"', seen[0][-1]["content"])
        self.assertNotIn("mahine", json.dumps(info))  # no quote in the trace

    async def test_a_matching_reply_passes_untouched(self) -> None:
        clean = AsyncMock(return_value={"conflicts": [], "unsupported": []})
        with patch.dict(os.environ, ON), patch("agent.runtime.steps.checks.check_reply_facts", clean):
            self.assertEqual(await check_facts(REPLY, job(AsyncMock())), (REPLY, {"checked": True, "conflicts": 0, "unsupported": 0}))

    async def test_it_runs_only_when_switched_on_and_something_was_looked_up(self) -> None:
        checker = AsyncMock(return_value=FOUND)
        with patch("agent.runtime.steps.checks.check_reply_facts", checker):
            with patch.dict(os.environ, {"AGENT_FACT_CHECK": ""}):
                self.assertEqual(await check_facts(REPLY, job(AsyncMock())), (REPLY, None))
            with patch.dict(os.environ, ON):
                self.assertEqual(await check_facts(REPLY, job(AsyncMock(), [{"role": "user", "content": "hi"}])), (REPLY, None))
        checker.assert_not_awaited()

    async def test_a_failing_checker_or_rewrite_keeps_the_draft(self) -> None:
        with patch.dict(os.environ, ON), patch("agent.runtime.steps.checks.check_reply_facts", AsyncMock(side_effect=RuntimeError("down"))):
            self.assertEqual(await check_facts(REPLY, job(AsyncMock())), (REPLY, {"checked": False, "error": "RuntimeError"}))
        with patch.dict(os.environ, ON), patch("agent.runtime.steps.checks.check_reply_facts", AsyncMock(return_value=FOUND)):
            kept, info = await check_facts(REPLY, job(AsyncMock(side_effect=RuntimeError("down"))))
        self.assertEqual((kept, info["rewritten"]), (REPLY, False))


if __name__ == "__main__":
    unittest.main()
