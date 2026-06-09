import unittest

from agent.extraction import normalize_extracted_profile
from agent.providers import _parse_json_object


class ExtractionQualityTest(unittest.TestCase):
    def test_normalizes_messy_model_profile(self) -> None:
        profile = normalize_extracted_profile(
            {
                "display_name": "  Aarav  ",
                "city": {"value": " Bengaluru ", "source": "user_stated", "confidence": 0.9},
                "relationship_intent": {
                    "value": "long_term",
                    "source": "user_stated",
                    "confidence": 0.8,
                },
                "values": {
                    "values": ["Family", "emotional stability", "Family"],
                    "source": "inferred",
                    "confidence": 0.7,
                },
                "dealbreakers": {
                    "values": "smoking, casual intent",
                    "source": "user_stated",
                    "confidence": 0.9,
                },
                "unknown_extra": "ignored",
            },
            "groq",
        )

        self.assertEqual(profile["agent_provider"], "groq")
        self.assertEqual(profile["display_name"], "Aarav")
        self.assertEqual(profile["city"]["value"], "Bengaluru")
        self.assertEqual(profile["values"]["values"], ["family", "emotional_stability"])
        self.assertEqual(profile["dealbreakers"]["values"], ["smoking", "casual_intent"])

    def test_adds_warnings_for_missing_important_fields(self) -> None:
        profile = normalize_extracted_profile({}, "ollama")

        self.assertIn("relationship_intent is unknown", profile["extraction_warnings"])
        self.assertIn("values are missing", profile["extraction_warnings"])
        self.assertIn("dealbreakers are missing", profile["extraction_warnings"])

    def test_extracts_json_from_markdown_response(self) -> None:
        parsed = _parse_json_object(
            '```json\n{"relationship_intent": {"value": "long_term"}}\n```'
        )

        self.assertEqual(parsed["relationship_intent"]["value"], "long_term")


if __name__ == "__main__":
    unittest.main()
