"""The chat search eval's seed and checks, without model calls."""

import unittest

from agent.evals.memory.chat_search import QUESTIONS, check_search_answer, seed_user
from agent.memory_engine.search import search_chats
from storage import reset_db


class ChatSearchEvalTest(unittest.TestCase):
    def test_the_seeded_lines_are_findable(self) -> None:
        reset_db()
        user_id = seed_user()
        self.assertTrue(any("14 December" in line for hit in search_chats(user_id, "engagement") for line in hit.lines))
        self.assertTrue(any("pottery" in line for hit in search_chats(user_id, "", days=7) for line in hit.lines))

    def test_checks(self) -> None:
        by_id = {q.id: q for q in QUESTIONS}
        searched = {"query": "engagement", "hits": 1}
        self.assertEqual(check_search_answer(by_id["engagement_date"], "14 December ko hai!", searched), "")
        self.assertEqual(check_search_answer(by_id["engagement_date"], "14 December ko hai!", None), "did not search")
        self.assertIn("does not know", check_search_answer(by_id["trap_rohan_age"], "Rohan 27 ka hai.", searched))
        self.assertEqual(check_search_answer(by_id["small_talk"], "Hey!", searched), "searched for small talk")


if __name__ == "__main__":
    unittest.main()
