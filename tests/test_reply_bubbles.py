import unittest

from agent.context_engine.conversation_engine.policy.replies import (
    MAX_REPLY_PARTS,
    REPLY_PART_SEPARATOR,
    split_assistant_reply,
)
from agent.context_engine.prompt_engine.modules.output_format import output_format_prompt


class ReplyBubbleTest(unittest.TestCase):
    def test_story_can_use_up_to_seven_bubbles(self) -> None:
        story = REPLY_PART_SEPARATOR.join(f"Part {index} of the story." for index in range(1, 10))
        parts = split_assistant_reply(story)

        self.assertEqual(MAX_REPLY_PARTS, 7)
        self.assertEqual(parts, [f"Part {index} of the story." for index in range(1, 8)])

    def test_normal_reply_stays_one_bubble(self) -> None:
        self.assertEqual(split_assistant_reply("haha fair, same here"), ["haha fair, same here"])

    def test_long_bubble_splits_at_sentence_ends_not_mid_sentence(self) -> None:
        first = "The chai stall opened at dawn and the old man hummed an RD Burman song while the kettle boiled slowly."
        second = "Nobody in the lane knew his real name, but everyone knew his laugh and the way he wiped each glass twice."
        parts = split_assistant_reply(f"hmm {REPLY_PART_SEPARATOR} {first} {second}")

        self.assertEqual(parts, ["hmm", first, second])

    def test_prompt_allows_short_splits_and_longer_stories(self) -> None:
        prompt = output_format_prompt()
        self.assertIn("2-3 bubbles", prompt)
        self.assertIn("up to 7 bubbles", prompt)
        self.assertIn("want me to continue?", prompt)


if __name__ == "__main__":
    unittest.main()
