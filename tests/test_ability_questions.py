"""The ability question list stays well formed, covers every area, and matches its readable page."""

import unittest
from pathlib import Path

from agent.evals.abilities.questions import AREAS, ASKED, NEEDS, QUESTIONS, as_markdown, coverage


class AbilityQuestionsTest(unittest.TestCase):
    def test_every_question_is_tagged_with_known_values_and_a_unique_id(self) -> None:
        ids = [question.id for question in QUESTIONS]
        self.assertEqual(len(ids), len(set(ids)))
        for question in QUESTIONS:
            self.assertIn(question.area, AREAS, question.id)
            self.assertIn(question.needs, NEEDS, question.id)
            self.assertIn(question.asked, ASKED, question.id)
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

    def test_the_readable_page_matches_the_list(self) -> None:
        page = Path(__file__).resolve().parents[1] / "docs" / "ability-questions.md"
        self.assertEqual(page.read_text(), as_markdown(), "run: PYTHONPATH=src python -m agent.evals.abilities.questions > docs/ability-questions.md")


if __name__ == "__main__":
    unittest.main()
