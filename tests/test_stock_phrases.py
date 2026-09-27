"""Stock lines are learned from chats: short companion lines repeated across many of them."""

import json
import tempfile
import unittest
from pathlib import Path

from agent.context_engine.conversation_engine.policy.freshness import stale_reply_reason
from agent.context_engine.conversation_engine.policy.stock_phrases import (
    STOCK_PHRASES,
    find_stock_lines,
    learned_stock_phrases,
    save_learned_phrases,
)


def _chat(*replies: str) -> list[dict]:
    messages = [{"role": "assistant", "content": "Hey Sam, I'm Annie."}]
    for reply in replies:
        messages += [{"role": "user", "content": "hmm"}, {"role": "assistant", "content": reply}]
    return messages


class FindStockLinesTest(unittest.TestCase):
    def test_lines_repeated_across_chats_are_found(self) -> None:
        chats = [_chat("Aww, that sounds so cozy!", f"Pune suits you {n}") for n in range(5)]
        chats.append(_chat("That sounds so cozy"))
        self.assertEqual(find_stock_lines(chats, min_conversations=5), [("aww that sounds so cozy", 5)])

    def test_repeats_inside_one_chat_short_lines_and_greetings_do_not_count(self) -> None:
        one_chat = _chat(*["Aww, that sounds so cozy!"] * 6)
        short = [_chat("haha ok") for _ in range(6)]
        greetings_only = [_chat() for _ in range(6)]
        self.assertEqual(find_stock_lines([one_chat, *short, *greetings_only], min_conversations=2), [])


class LearnedListTest(unittest.TestCase):
    def test_saved_lines_merge_and_reload(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "learned.json"
            save_learned_phrases(["Aww, that sounds so cozy!"], path)
            save_learned_phrases(["you deserve it"], path)
            self.assertEqual(learned_stock_phrases(path), ("aww that sounds so cozy", "you deserve it"))
            self.assertIn("Remove a line", json.loads(path.read_text())["note"])

    def test_missing_or_broken_file_means_no_learned_lines(self) -> None:
        self.assertEqual(learned_stock_phrases(Path("/nonexistent/learned.json")), ())

    def test_the_reply_check_uses_seed_and_learned_lines(self) -> None:
        self.assertIn("that sounds like fun", STOCK_PHRASES)
        self.assertIsNotNone(stale_reply_reason("That sounds like fun!", []))


if __name__ == "__main__":
    unittest.main()
