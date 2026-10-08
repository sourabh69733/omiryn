"""Background memory sees which earlier message the user picked to answer."""

import json
import unittest

from agent.memory_engine.processing.context import build_memory_batch
from agent.memory_engine.processing.prompt import memory_batch_prompt

MESSAGES = [
    {"role": "assistant", "content": "Do you still play chess?", "created_at": "2026-10-01T10:00:00+00:00"},
    {"role": "assistant", "content": "And how was the trip?", "created_at": "2026-10-01T10:00:05+00:00"},
    {
        "role": "user",
        "content": "Yes, every weekend.",
        "created_at": "2026-10-01T10:01:00+00:00",
        "reply_to": {"index": 0, "role": "assistant", "text": "Do you still play chess?"},
    },
    {
        "role": "user",
        "content": "Ok",
        "created_at": "2026-10-01T10:02:00+00:00",
        "reply_to": {"index": 1, "deleted": True},
    },
]


class ReplyQuoteMemoryTest(unittest.TestCase):
    def test_the_quote_reaches_the_background_model(self) -> None:
        batch = build_memory_batch(conversation_id="chat", user_id="user", messages=MESSAGES)
        payload = json.loads(memory_batch_prompt(batch, []))
        by_index = {message["message_index"]: message for message in payload["messages"]}

        self.assertEqual(by_index[2]["replying_to"], {"message_index": 0, "text": "Do you still play chess?"})
        # A quote of a deleted message is not passed on.
        self.assertNotIn("replying_to", by_index[3])
        self.assertNotIn("replying_to", by_index[0])


if __name__ == "__main__":
    unittest.main()
