import unittest
from unittest.mock import patch

from agent.providers import _provider_messages
from agent.shared.tokens import estimate_tokens


def _chat(count: int, content: str = "short message") -> list[dict]:
    return [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"{index} {content}"}
        for index in range(count)
    ]


class EstimateTokensTest(unittest.TestCase):
    def test_ascii_is_about_four_characters_per_token(self) -> None:
        self.assertEqual(estimate_tokens("a" * 400), 100)

    def test_other_scripts_count_higher(self) -> None:
        self.assertEqual(estimate_tokens("नमस्ते"), 3)
        self.assertEqual(estimate_tokens(""), 0)


@patch("agent.providers.shared.messages.RECENT_CHAT_MESSAGE_LIMIT", 24)
class HistoryBudgetTest(unittest.TestCase):
    def test_history_within_budget_is_unchanged(self) -> None:
        messages = _chat(10)
        self.assertEqual([m["content"] for m in _provider_messages(messages)], [m["content"] for m in messages])

    @patch("agent.providers.shared.messages.HISTORY_TOKEN_BUDGET", 1500)
    def test_long_old_messages_are_shortened_before_anything_is_dropped(self) -> None:
        messages = _chat(10)
        messages[1]["content"] = "pasted " * 900  # ~1600 tokens, old assistant message
        fitted = _provider_messages(messages)

        self.assertEqual(len(fitted), 10)
        self.assertLessEqual(len(fitted[1]["content"]), 1200)
        self.assertEqual(fitted[-1]["content"], "9 short message")

    @patch("agent.providers.shared.messages.HISTORY_TOKEN_BUDGET", 400)
    def test_oldest_messages_are_dropped_but_newest_four_always_stay(self) -> None:
        messages = _chat(20, "x" * 300)  # ~76 tokens each
        fitted = _provider_messages(messages)

        self.assertLess(len(fitted), 20)
        self.assertEqual(fitted[-1]["content"], messages[-1]["content"])
        self.assertLessEqual(sum(estimate_tokens(m["content"]) for m in fitted), 400)

    @patch("agent.providers.shared.messages.HISTORY_TOKEN_BUDGET", 10)
    def test_newest_four_survive_even_an_impossible_budget(self) -> None:
        messages = _chat(8, "y" * 2000)
        fitted = _provider_messages(messages)

        self.assertEqual(len(fitted), 4)
        self.assertEqual(fitted[-1]["content"], messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()
