"""A reply the model wrote reaches the user whole: long ones become bubbles, nothing is dropped."""

import unittest

from agent.context_engine.policy.replies import (
    MAX_REPLY_PARTS,
    MAX_REPLY_WORDS,
    REPLY_PART_WORD_LIMIT,
    sentences,
    split_assistant_reply,
)
from agent.providers.shared.messages import _compact_chat_reply

PF_STEPS = (
    "Haan, online ho jaata hai, bas UAN active hona chahiye. "
    "1. EPFO member portal pe UAN aur password se login karo "
    "2. KYC mein Aadhaar, PAN aur bank account verified hone chahiye, warna claim reject hota hai. "
    "3. Online Services mein Claim (Form-31, 19, 10C) kholo aur bank account ke last 4 digit daalo. "
    "4. Form 19 PF ke liye aur Form 10C pension ke liye chuno, phir Aadhaar OTP se submit karo. "
    "Paisa aam taur pe 7 se 20 din mein bank mein aa jaata hai. "
    "Ek cheez: job chhodne ke 2 mahine baad hi full withdrawal khulta hai."
)
ASKED_IN_HINGLISH = [{"role": "user", "content": "job chhodne ke baad pf kaise nikalte hain"}]


class ReplyLengthTest(unittest.TestCase):
    def test_steps_asked_for_in_hinglish_reach_the_user_whole(self) -> None:
        reply = _compact_chat_reply(PF_STEPS, ASKED_IN_HINGLISH)
        parts = split_assistant_reply(reply)

        self.assertEqual(reply, PF_STEPS)
        self.assertEqual(" ".join(parts), PF_STEPS)
        self.assertLessEqual(len(parts), MAX_REPLY_PARTS)

    def test_a_step_number_stays_with_its_step(self) -> None:
        parts = split_assistant_reply(PF_STEPS)

        self.assertFalse([part for part in parts if part.rstrip().endswith(("1.", "2.", "3.", "4."))])
        self.assertIn("2. KYC mein Aadhaar", " | ".join(sentences(PF_STEPS)))
        self.assertTrue(all(not sentence[:-1].isdigit() for sentence in sentences(PF_STEPS)))

    def test_text_without_a_list_splits_at_sentence_ends_only(self) -> None:
        self.assertEqual(sentences("Room number 2. Phir seedha jao! Theek?"), ["Room number 2.", "Phir seedha jao!", "Theek?"])

    def test_short_reply_stays_one_bubble(self) -> None:
        self.assertEqual(split_assistant_reply("haan yaar, ye sahi lag raha hai. kal milte hain?"), ["haan yaar, ye sahi lag raha hai. kal milte hain?"])

    def test_bubbles_grow_when_a_reply_would_need_too_many(self) -> None:
        # Twelve 20-word sentences: at 35 words a bubble that is 12 bubbles, more than a reply may have.
        written = " ".join(" ".join([f"s{index}"] * 19) + " end." for index in range(12))
        parts = split_assistant_reply(written)

        self.assertEqual(" ".join(parts), written)
        self.assertLessEqual(len(parts), MAX_REPLY_PARTS)
        self.assertGreater(max(len(part.split()) for part in parts), REPLY_PART_WORD_LIMIT)

    def test_a_runaway_reply_ends_at_a_sentence(self) -> None:
        written = " ".join("yeh ek chhota sa vaakya hai." for _ in range(80))
        reply = _compact_chat_reply(written, ASKED_IN_HINGLISH)

        self.assertLessEqual(len(reply.split()), MAX_REPLY_WORDS)
        self.assertGreater(len(reply.split()), MAX_REPLY_WORDS - 10)
        self.assertTrue(reply.endswith("hai."))


class BubbleStartTest(unittest.TestCase):
    def test_a_time_at_the_start_is_kept(self) -> None:
        text = "Saturday 9:43 pm pe bhi kaam ka tension, ye theek nahi."
        self.assertEqual(split_assistant_reply(text), [text])

    def test_a_lead_in_before_a_colon_is_kept(self) -> None:
        for text in ("Ek catch: notice period buyout tumhe khud dena pad sakta hai.", "Short answer: haan, kar sakte ho.", "Note: last date 24 November hai."):
            with self.subTest(text=text):
                self.assertEqual(split_assistant_reply(text), [text])

    def test_the_agents_own_name_as_a_label_is_removed(self) -> None:
        self.assertEqual(split_assistant_reply("Omi: haan bolo"), ["haan bolo"])
        self.assertEqual(split_assistant_reply("hmm <next_message> Assistant: sun raha hoon"), ["hmm", "sun raha hoon"])

    def test_a_script_style_character_label_is_removed(self) -> None:
        self.assertEqual(split_assistant_reply('Rahul: "Chalo, ab ghar chalte hain."'), ["Chalo, ab ghar chalte hain."])


if __name__ == "__main__":
    unittest.main()
