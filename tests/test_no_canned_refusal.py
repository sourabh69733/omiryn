"""A stock refusal is never swapped for a fixed line; it is flagged so the model rewrites it."""

import unittest

from agent.context_engine.conversation_engine.policy import split_assistant_reply
from agent.context_engine.conversation_engine.policy.freshness import stale_reply_reason


class NoCannedRefusalTest(unittest.TestCase):
    def test_the_reply_is_kept_as_the_model_wrote_it(self) -> None:
        parts = split_assistant_reply("I'm sorry, but I can't help with that.", user_text="say something hot")

        self.assertEqual(parts, ["I'm sorry, but I can't help with that."])

    def test_a_stock_refusal_asks_for_a_rewrite(self) -> None:
        self.assertIn("stock line", stale_reply_reason("Sorry, I can't help with that.", []) or "")


if __name__ == "__main__":
    unittest.main()
