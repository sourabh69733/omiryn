"""Background prompts show formats with placeholders; example content leaked into real summaries."""

import re
import unittest

from agent.cognition.background.prompt_v3 import BACKGROUND_COGNITION_V3_SYSTEM_PROMPT

# Subjects that once served as examples and were copied into a user's summary as facts.
_ONCE_LEAKED = ("interview", "trip", "beagle", "bruno", "pune", "mumbai", "design studio", "long walks")


class PromptGroundingTest(unittest.TestCase):
    def test_background_prompt_has_no_example_subjects(self) -> None:
        text = BACKGROUND_COGNITION_V3_SYSTEM_PROMPT.casefold()
        for subject in _ONCE_LEAKED:
            with self.subTest(subject=subject):
                self.assertIsNone(re.search(rf"\b{re.escape(subject)}", text))

    def test_thin_batches_must_produce_nothing(self) -> None:
        self.assertIn("Never fill a field to seem useful", BACKGROUND_COGNITION_V3_SYSTEM_PROMPT)
        self.assertIn("conversation_summary null", BACKGROUND_COGNITION_V3_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
