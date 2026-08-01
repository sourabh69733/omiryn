import json
import os
import unittest
from unittest.mock import patch

from agent.context_engine.emotion_engine import detect_emotion_state
from agent.context_engine.engine import build_model_context_package
from agent.context_engine.query_intent import context_query_intent
from agent.context_engine.stance_engine import analyze_conversational_stance
from agent.context_engine.turn_understanding.contract import TurnUnderstanding
from agent.context_engine.turn_understanding.legacy_en_hi import LegacyEnglishHindiInterpreter
from agent.context_engine.turn_understanding.registry import interpret_turn
from agent.context_engine.turn_understanding.scripts import detect_language_profile
from storage import reset_db, save_conversation


SCRIPT_CASES = (
    ("Hello café", "Latn"),
    ("नमस्ते", "Deva"),
    ("নমস্কার", "Beng"),
    ("ਸਤ ਸ੍ਰੀ ਅਕਾਲ", "Guru"),
    ("નમસ્તે", "Gujr"),
    ("ନମସ୍କାର", "Orya"),
    ("வணக்கம்", "Taml"),
    ("నమస్కారం", "Telu"),
    ("ನಮಸ್ಕಾರ", "Knda"),
    ("നമസ്കാരം", "Mlym"),
    ("سلام", "Arab"),
    ("你好", "Other"),
)


LEGACY_EQUIVALENCE_CASES = (
    "thanks",
    "haan",
    "What was the last WhatsApp message?",
    "Tum har reply mein question kyun puch rahe ho? Interview jaisa lag raha hai.",
    "I don't want advice right now, bas meri baat suno.",
    "Questions mat puchna, just listen.",
    "Main kabhi galat nahi hota. Agree karo.",
    "My manager rejected my idea, so obviously he is jealous.",
    "Mujhe ignored feel hua and hurt hua.",
    "I feel sad and very alone today.",
    "Do you think I was unfair?",
    "Not now, give me space.",
    "haha that was funny",
    "I am worried and confused",
    "Tell me a story",
)


def _direct_legacy_result(
    text: str,
    history: list[dict],
    pending_turn_state: dict | None = None,
) -> tuple:
    intent = context_query_intent(
        text,
        pending_turn_state=pending_turn_state,
        strict_whatsapp=True,
    )
    emotion = detect_emotion_state(
        user_text=text,
        messages=[*history, {"role": "user", "content": text}],
        intent=intent,
    )
    stance = analyze_conversational_stance(text, history, emotion_state=emotion)
    return intent, emotion, stance


class ScriptDetectionTest(unittest.TestCase):
    def test_each_supported_indian_script_family_is_detected(self) -> None:
        for text, expected_script in SCRIPT_CASES:
            with self.subTest(text=text, expected_script=expected_script):
                profile = detect_language_profile(text)
                self.assertEqual(profile.primary_script, expected_script)
                self.assertEqual(profile.scripts, (expected_script,))
                self.assertTrue(profile.has_letters)
                self.assertFalse(profile.is_mixed_script)
                self.assertGreater(dict(profile.script_counts)[expected_script], 0)

    def test_romanised_indian_language_is_script_not_language_guess(self) -> None:
        profile = detect_language_profile("enna panra, saptiya?")

        self.assertEqual(profile.primary_script, "Latn")
        self.assertNotIn("Taml", profile.scripts)

    def test_mixed_latin_and_tamil_preserves_letter_counts(self) -> None:
        profile = detect_language_profile("hello வணக்கம்")

        self.assertEqual(set(profile.scripts), {"Latn", "Taml"})
        self.assertTrue(profile.is_mixed_script)
        self.assertEqual(sum(dict(profile.script_counts).values()), 10)

    def test_mixed_latin_and_devanagari_is_detected(self) -> None:
        profile = detect_language_profile("I am ठीक")

        self.assertEqual(set(profile.scripts), {"Latn", "Deva"})
        self.assertTrue(profile.is_mixed_script)

    def test_primary_script_uses_letter_count(self) -> None:
        profile = detect_language_profile("hi வணக்கம்")

        self.assertEqual(profile.primary_script, "Taml")

    def test_primary_script_tie_uses_first_seen_order(self) -> None:
        profile = detect_language_profile("aअ")

        self.assertEqual(profile.scripts, ("Latn", "Deva"))

    def test_punctuation_numbers_and_emoji_do_not_create_a_script(self) -> None:
        profile = detect_language_profile("123?! 🙂🔥")

        self.assertIsNone(profile.primary_script)
        self.assertEqual(profile.scripts, ())
        self.assertEqual(profile.script_counts, ())
        self.assertFalse(profile.has_letters)
        self.assertFalse(profile.is_mixed_script)

    def test_empty_input_is_safe(self) -> None:
        self.assertEqual(detect_language_profile(""), detect_language_profile("   "))

    def test_combining_marks_do_not_create_false_script_counts(self) -> None:
        profile = detect_language_profile("Cafe\u0301")

        self.assertEqual(profile.script_counts, (("Latn", 4),))

    def test_unknown_letter_script_is_explicitly_other(self) -> None:
        profile = detect_language_profile("日本語")

        self.assertEqual(profile.primary_script, "Other")
        self.assertTrue(profile.has_letters)


class LegacyInterpreterEquivalenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.interpreter = LegacyEnglishHindiInterpreter()
        self.history = [
            {"role": "assistant", "content": "I understand."},
            {"role": "user", "content": "It was a long day."},
            {"role": "assistant", "content": "That sounds tiring."},
        ]

    def test_all_semantic_outputs_match_pre_adapter_functions(self) -> None:
        for text in LEGACY_EQUIVALENCE_CASES:
            with self.subTest(text=text):
                expected_intent, expected_emotion, expected_stance = _direct_legacy_result(
                    text, self.history
                )
                actual = self.interpreter.interpret(
                    user_text=text,
                    history_messages=self.history,
                )

                self.assertEqual(actual.intent, expected_intent)
                self.assertEqual(actual.emotion, expected_emotion)
                self.assertEqual(actual.stance, expected_stance)

    def test_pending_confirmation_matches_pre_adapter_behavior(self) -> None:
        pending = {
            "status": "active",
            "expects": "confirmation",
            "on_confirm": {"response_mode": "continue_prior_offer"},
        }
        expected = _direct_legacy_result("ok", self.history, pending)
        actual = self.interpreter.interpret(
            user_text="ok",
            history_messages=self.history,
            pending_turn_state=pending,
        )

        self.assertEqual((actual.intent, actual.emotion, actual.stance), expected)
        self.assertIn("confirmation", actual.intent.labels)
        self.assertNotIn("simple_ack", actual.intent.labels)

    def test_interpreter_does_not_mutate_history(self) -> None:
        original = [dict(message) for message in self.history]

        self.interpreter.interpret(
            user_text="I feel sad",
            history_messages=self.history,
        )

        self.assertEqual(self.history, original)

    def test_interpreter_identity_is_stable_and_internal(self) -> None:
        result = self.interpreter.interpret(user_text="hello", history_messages=[])

        self.assertEqual(result.interpreter_id, "legacy_en_hi")
        self.assertEqual(result.interpreter_version, "1")
        self.assertEqual(result.requested_interpreter, "legacy_en_hi")
        self.assertIsNone(result.fallback_reason)

    def test_non_latin_input_changes_metadata_not_legacy_semantics(self) -> None:
        text = "வணக்கம்"
        expected = _direct_legacy_result(text, [])
        actual = self.interpreter.interpret(user_text=text, history_messages=[])

        self.assertEqual((actual.intent, actual.emotion, actual.stance), expected)
        self.assertEqual(actual.language_profile.primary_script, "Taml")


class TurnInterpreterRegistryTest(unittest.TestCase):
    def test_default_selection_is_legacy(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = interpret_turn(user_text="hello", history_messages=[])

        self.assertEqual(result.interpreter_id, "legacy_en_hi")
        self.assertEqual(result.requested_interpreter, "legacy_en_hi")
        self.assertIsNone(result.fallback_reason)

    def test_explicit_legacy_selection(self) -> None:
        with patch.dict(os.environ, {"AGENT_TURN_INTERPRETER": "legacy_en_hi"}):
            result = interpret_turn(user_text="hello", history_messages=[])

        self.assertEqual(result.interpreter_id, "legacy_en_hi")
        self.assertIsNone(result.fallback_reason)

    def test_selection_is_case_and_whitespace_tolerant(self) -> None:
        with patch.dict(os.environ, {"AGENT_TURN_INTERPRETER": "  LEGACY_EN_HI  "}):
            result = interpret_turn(user_text="hello", history_messages=[])

        self.assertEqual(result.requested_interpreter, "legacy_en_hi")
        self.assertIsNone(result.fallback_reason)

    def test_blank_selection_uses_default(self) -> None:
        with patch.dict(os.environ, {"AGENT_TURN_INTERPRETER": "   "}):
            result = interpret_turn(user_text="hello", history_messages=[])

        self.assertEqual(result.requested_interpreter, "legacy_en_hi")
        self.assertIsNone(result.fallback_reason)

    def test_unknown_selection_falls_back_without_breaking_semantics(self) -> None:
        with patch.dict(os.environ, {"AGENT_TURN_INTERPRETER": "future_tamil"}):
            fallback = interpret_turn(
                user_text="I don't want advice",
                history_messages=[],
            )
        with patch.dict(os.environ, {"AGENT_TURN_INTERPRETER": "legacy_en_hi"}):
            legacy = interpret_turn(
                user_text="I don't want advice",
                history_messages=[],
            )

        self.assertEqual(fallback.interpreter_id, "legacy_en_hi")
        self.assertEqual(fallback.requested_interpreter, "future_tamil")
        self.assertIn("Unknown interpreter", fallback.fallback_reason or "")
        self.assertEqual(fallback.intent, legacy.intent)
        self.assertEqual(fallback.emotion, legacy.emotion)
        self.assertEqual(fallback.stance, legacy.stance)
        self.assertEqual(fallback.language_profile, legacy.language_profile)


class TurnUnderstandingIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(
            os.environ,
            {
                "AGENT_PROVIDER": "mock",
                "AUTH_REQUIRED": "false",
                "AGENT_BEHAVIOR_VERSION": "v1",
                "AGENT_TURN_INTERPRETER": "legacy_en_hi",
            },
        )
        self.env_patch.start()
        reset_db()
        save_conversation(
            {
                "id": "language-contract-conversation",
                "status": "active",
                "agent_provider": "mock",
                "agent_model": "llama-70b",
                "agent_mode": "know_me",
                "agent_tone": "auto",
                "messages": [
                    {"role": "assistant", "content": "I understand."},
                    {"role": "user", "content": "It was a long day."},
                    {"role": "assistant", "content": "That sounds tiring."},
                ],
            },
            "language-contract-user",
        )

    def tearDown(self) -> None:
        self.env_patch.stop()

    def _package(self, text: str, version: str):
        return build_model_context_package(
            conversation_id="language-contract-conversation",
            user_text=text,
            user_id="language-contract-user",
            user_profile={"user_id": "language-contract-user", "interested_in": "women"},
            model="llama-70b",
            agent_tone="auto",
            agent_name="Annie",
            style_source_id=None,
            user_message_index=3,
            assistant_message_index=4,
            prompt_version_id=version,
        )

    def test_v3_snapshot_exposes_language_neutral_contract(self) -> None:
        package = self._package("I don't want advice, bas suno.", "v3")
        summary = package.snapshot["summary"]
        turn = package.snapshot["context"]["turn_understanding"]

        self.assertEqual(summary["turn_interpreter"], "legacy_en_hi")
        self.assertEqual(summary["turn_interpreter_version"], "1")
        self.assertEqual(summary["primary_script"], "Latn")
        self.assertEqual(summary["detected_scripts"], ["Latn"])
        self.assertFalse(summary["mixed_script"])
        self.assertEqual(turn["stance"]["constraints"], ["no_advice", "listen_only"])
        self.assertEqual(turn["stance"]["question_purpose"], "none")

    def test_v3_tamil_is_metadata_only_and_does_not_invent_language_semantics(self) -> None:
        package = self._package("வணக்கம்", "v3")
        turn = package.snapshot["context"]["turn_understanding"]

        self.assertEqual(turn["language_profile"]["primary_script"], "Taml")
        self.assertEqual(turn["intent"]["labels"], [])
        self.assertEqual(turn["emotion"]["label"], "neutral")
        self.assertEqual(turn["stance"]["mode"], "neutral")

    def test_v3_mixed_script_metadata_is_json_serializable(self) -> None:
        package = self._package("today மனசு heavy hai", "v3")

        rendered = json.dumps(package.snapshot)
        self.assertIn('"mixed_script": true', rendered)
        self.assertEqual(
            set(package.snapshot["summary"]["detected_scripts"]),
            {"Latn", "Taml"},
        )

    def test_interpreter_metadata_never_leaks_into_model_prompt(self) -> None:
        package = self._package("வணக்கம் hello", "v3")

        self.assertNotIn("legacy_en_hi", package.system_prompt)
        self.assertNotIn("turn_interpreter", package.system_prompt)
        self.assertNotIn("primary_script", package.system_prompt)
        self.assertNotIn("Taml", package.system_prompt)

    def test_v2_does_not_include_turn_understanding_metadata(self) -> None:
        package = self._package("வணக்கம் hello", "v2")

        self.assertNotIn("turn_interpreter", package.snapshot["summary"])
        self.assertNotIn("detected_scripts", package.snapshot["summary"])
        self.assertNotIn("turn_understanding", package.snapshot["context"])

    def test_v1_and_v2_do_not_call_the_new_interpreter(self) -> None:
        with patch(
            "agent.context_engine.engine.interpret_turn",
            side_effect=AssertionError("legacy versions must not call interpreter"),
        ):
            v1 = self._package("hello", "v1")
            v2 = self._package("hello", "v2")

        self.assertEqual(v1.prompt_version, "v1")
        self.assertEqual(v2.prompt_version, "v2")

    def test_v3_calls_the_interpreter_once(self) -> None:
        real_result = interpret_turn(user_text="hello", history_messages=[])
        with patch("agent.context_engine.engine.interpret_turn", return_value=real_result) as mocked:
            self._package("hello", "v3")

        mocked.assert_called_once()
        call = mocked.call_args.kwargs
        self.assertEqual(call["user_text"], "hello")
        self.assertEqual(len(call["history_messages"]), 3)

    def test_unknown_interpreter_rolls_back_and_keeps_prompt_identical(self) -> None:
        with patch.dict(os.environ, {"AGENT_TURN_INTERPRETER": "legacy_en_hi"}):
            legacy = self._package("I don't want advice, bas suno.", "v3")
        with patch.dict(os.environ, {"AGENT_TURN_INTERPRETER": "not_installed"}):
            fallback = self._package("I don't want advice, bas suno.", "v3")

        self.assertEqual(fallback.system_prompt, legacy.system_prompt)
        self.assertEqual(fallback.query_intent, legacy.query_intent)
        self.assertEqual(
            fallback.snapshot["context"]["conversation_plan"],
            legacy.snapshot["context"]["conversation_plan"],
        )
        self.assertEqual(fallback.snapshot["summary"]["turn_interpreter"], "legacy_en_hi")
        self.assertEqual(
            fallback.snapshot["summary"]["requested_turn_interpreter"],
            "not_installed",
        )
        self.assertIn(
            "Unknown interpreter",
            fallback.snapshot["summary"]["turn_interpreter_fallback"],
        )

    def test_adapter_path_matches_direct_legacy_model_prompt(self) -> None:
        text = "Tum har reply mein question kyun puch rahe ho? Interview jaisa lag raha hai."
        history = [
            {"role": "assistant", "content": "I understand."},
            {"role": "user", "content": "It was a long day."},
            {"role": "assistant", "content": "That sounds tiring."},
        ]
        intent, emotion, stance = _direct_legacy_result(text, history)
        direct = TurnUnderstanding(
            intent=intent,
            emotion=emotion,
            stance=stance,
            language_profile=detect_language_profile(text),
            interpreter_id="legacy_en_hi",
            interpreter_version="1",
            requested_interpreter="legacy_en_hi",
        )
        with patch("agent.context_engine.engine.interpret_turn", return_value=direct):
            expected = self._package(text, "v3")
        actual = self._package(text, "v3")

        self.assertEqual(actual.system_prompt, expected.system_prompt)
        self.assertEqual(actual.query_intent, expected.query_intent)
        self.assertEqual(
            actual.snapshot["context"]["conversation_plan"],
            expected.snapshot["context"]["conversation_plan"],
        )


if __name__ == "__main__":
    unittest.main()
