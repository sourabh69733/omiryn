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


class ReplyPromptGroundingTest(unittest.TestCase):
    def test_reply_prompt_carries_no_example_names(self) -> None:
        import os
        from unittest.mock import patch

        from agent.context_engine.engine import build_model_context_package
        from storage import reset_db, save_conversation

        reset_db()
        save_conversation({"id": "c", "status": "active", "messages": []}, "u")
        with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"}):
            prompt = build_model_context_package(
                conversation_id="c", user_text="tell me a story", user_id="u", user_profile={},
                model=None, agent_tone="auto", agent_name=None, style_source_id=None,
                user_message_index=0, assistant_message_index=1,
            ).system_prompt.casefold()
        # Names once used as examples; a story or reply could reuse them as if real.
        for name in ("rahul", "siya", "abhishek", "bruno", "riya"):
            with self.subTest(name=name):
                self.assertIsNone(re.search(rf"\b{name}\b", prompt))
