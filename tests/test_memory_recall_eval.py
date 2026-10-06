"""The recall eval seeds memories from other chats and checks found/answered in code."""

import os
import unittest
from unittest.mock import patch

from agent.evals.memory.recall import RECALL_CASES, _answer_problems, recall_environment, run_recall_case
from storage import reset_db

CASES = {case.id: case for case in RECALL_CASES}


class RecallEvalTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()

    async def test_a_memory_from_another_chat_is_found_in_the_prompt(self) -> None:
        env = {**recall_environment("mock", "v4"), "MEMORY_EMBEDDING_MODEL": "off"}
        with patch.dict(os.environ, env):
            result = await run_recall_case(CASES["who_is_my_wife"], provider="mock", model=None)

        self.assertTrue(result.found, result.missing_memories)

    def test_answers_are_checked_by_group_and_wording(self) -> None:
        case = CASES["wife_and_anniversary"]

        self.assertEqual(_answer_problems(case, "Priya! You two married on 20th Nov."), ())
        self.assertEqual(len(_answer_problems(case, "Priya, of course.")), 1)
        self.assertIn("asked 1 question(s)", _answer_problems(CASES["how_to_talk"], "Want a fact?"))


if __name__ == "__main__":
    unittest.main()
