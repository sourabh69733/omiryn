"""The ability question list stays well formed, covers every area, and matches its readable page."""

import unittest
from pathlib import Path

from agent.evals.abilities.questions import AREAS, ASKED, NEEDS, QUESTIONS, WHO, as_markdown, coverage


class AbilityQuestionsTest(unittest.TestCase):
    def test_every_question_is_tagged_with_known_values_and_a_unique_id(self) -> None:
        ids = [question.id for question in QUESTIONS]
        self.assertEqual(len(ids), len(set(ids)))
        for question in QUESTIONS:
            self.assertIn(question.area, AREAS, question.id)
            self.assertIn(question.needs, NEEDS, question.id)
            self.assertIn(question.asked, ASKED, question.id)
            self.assertIn(question.who, WHO, question.id)
            self.assertTrue(question.text.strip() and question.right_when.strip(), question.id)

    def test_a_follow_up_comes_right_after_the_question_it_follows(self) -> None:
        ids = [question.id for question in QUESTIONS]
        for index, question in enumerate(QUESTIONS):
            if question.after:
                self.assertEqual(ids[index - 1], question.after, question.id)

    def test_every_area_and_every_need_has_questions(self) -> None:
        counts = coverage()
        for area in AREAS:
            self.assertGreaterEqual(counts["area"][area], 3, area)
        for need in NEEDS:
            self.assertGreaterEqual(counts["needs"][need], 2, need)

    def test_career_gives_each_stage_the_same_spread(self) -> None:
        # A student, a final-year and a working person each get: something to look up, a decision,
        # something to write, a hard moment to talk through, and one that uses what Omi knows.
        for who in ("student", "finishing", "working"):
            needs = {question.needs for question in QUESTIONS if question.area == "career" and question.who == who}
            self.assertGreaterEqual(sum(1 for q in QUESTIONS if q.area == "career" and q.who == who), 10, who)
            self.assertTrue(needs & {"look_up", "look_up_dates", "look_up_deep"}, who)
            self.assertTrue(needs & {"memory", "memory_and_look_up"}, who)
            for need in ("decide", "write", "talk"):
                self.assertIn(need, needs, f"{who} has no {need} question")

    def test_the_readable_page_matches_the_list(self) -> None:
        page = Path(__file__).resolve().parents[1] / "docs" / "ability-questions.md"
        self.assertEqual(page.read_text(), as_markdown(), "run: PYTHONPATH=src python -m agent.evals.abilities.questions > docs/ability-questions.md")


if __name__ == "__main__":
    unittest.main()
