import os
import unittest
from unittest.mock import patch

from agent.context_engine.engine import build_model_context_package
from agent.context_engine.prompt_engine.modules.behavior import build_companion_behavior
from agent.context_engine.prompt_engine.modules.identity import (
    agent_persona_for_interest,
    persona_card_prompt,
)
from storage import reset_db, save_conversation


class PersonaCardTest(unittest.TestCase):
    def test_each_character_has_its_own_card_and_hindi_grammar(self) -> None:
        cases = {
            "women": ("Annie", "main thak gayi"),
            "men": ("Kabir", "main thak gaya"),
            "": ("Omi", "mujhe laga"),
        }
        for interest, (name, grammar) in cases.items():
            with self.subTest(interest=interest):
                persona = agent_persona_for_interest(interest)
                card = persona_card_prompt(persona["card"], persona["name"])
                self.assertEqual(persona["name"], name)
                self.assertIn(f"You are {name}.", card)
                self.assertIn(grammar, card)
                self.assertIn("What's on your mind today?", card)  # listed as a line to avoid
                self.assertIn("Say you are an AI if asked", card)

    @patch.dict(os.environ, {"AGENT_PERSONA_CARDS_ENABLED": "true"})
    def test_renamed_agent_keeps_character_with_new_name(self) -> None:
        behavior = build_companion_behavior({}, agent_name="Rohan", voice="male")
        self.assertTrue(behavior.persona_card.startswith("You are Rohan."))
        self.assertIn("Test cricket", behavior.persona_card)
        self.assertNotIn("{name}", behavior.persona_card)

    def test_cards_are_off_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT_PERSONA_CARDS_ENABLED", None)
            self.assertEqual(build_companion_behavior({"interested_in": "men"}).persona_card, "")


class PersonaPromptTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": "c", "status": "active", "messages": []}, "u")

    def _prompt(self, cards: str = "false") -> str:
        env = {
            "AGENT_PIPELINE_VERSION": "v3",
            "MEMORY_EMBEDDING_MODEL": "off",
            "AGENT_PERSONA_CARDS_ENABLED": cards,
        }
        with patch.dict(os.environ, env):
            return build_model_context_package(
                conversation_id="c",
                user_text="chai or coffee?",
                user_id="u",
                user_profile={"interested_in": "women"},
                model=None,
                agent_tone="auto",
                agent_name=None,
                style_source_id=None,
                user_message_index=0,
                assistant_message_index=1,
            ).system_prompt

    def test_disabled_cards_leave_no_character_section(self) -> None:
        self.assertNotIn("## Your Character", self._prompt())

    def test_enabled_card_follows_core_identity(self) -> None:
        save_conversation({"id": "c", "status": "active", "messages": [], "agent_voice": "female"}, "u")
        prompt = self._prompt(cards="true")
        self.assertLess(prompt.index("## Core Identity"), prompt.index("## Your Character"))
        self.assertLess(prompt.index("## Your Character"), prompt.index("## Prompt Contract"))
        self.assertIn("Team chai, strongly.", prompt)

    def test_prompt_budget_keeps_every_fixed_section_whole(self) -> None:
        prompt = self._prompt(cards="true")
        for heading in ("## Tone", "## Output Format", "## Final Reminder"):
            with self.subTest(heading=heading):
                start = prompt.index(heading)
                section = prompt[start:].split("\n## ", 1)[0]
                self.assertGreater(len(section), len(heading) + 40)


if __name__ == "__main__":
    unittest.main()
