"""The uploaded-chat eval's fixture and checks, without model calls."""

import unittest
from zoneinfo import ZoneInfo

from agent.evals.memory.upload_chats import EXPORT, QUESTIONS, check_answer, check_reading
from ingestion.upload_chat import whatsapp_upload_messages


class UploadChatEvalTest(unittest.TestCase):
    def test_the_fixture_has_both_sides(self) -> None:
        messages = whatsapp_upload_messages(EXPORT, "Sourabh", ZoneInfo("Asia/Kolkata"))
        self.assertEqual({m["role"] for m in messages}, {"user", "other"})
        self.assertEqual({m.get("speaker") for m in messages if m["role"] == "other"}, {"Ananya"})

    def test_answers_are_checked_by_fact_trap_and_small_talk(self) -> None:
        by_id = {q.id: q for q in QUESTIONS}
        self.assertEqual(check_answer(by_id["her_city"], "Woh Indore mein rehti hai."), "")
        self.assertIn("missing", check_answer(by_id["her_city"], "Pune mein."))
        self.assertEqual(check_answer(by_id["trap_movie"], "Yeh chat mein nahi aaya, mujhe nahi pata."), "")
        self.assertIn("does not know", check_answer(by_id["trap_movie"], "Uski favourite movie Titanic hai."))
        self.assertIn("brought up", check_answer(by_id["small_talk"], "Hey! Mochi kaisi hai?"))

    def test_reading_flags_a_friend_fact_saved_as_the_user(self) -> None:
        digest = {"index_line": "x", "threads": [{"title": "Crypto debate"}, {"title": "Sinhagad trek"}], "person": [{"text": "Lives in Indore, teaches maths, has a cat Mochi."}]}
        memories = ("thinks crypto is gambling.", "plays badminton weekly.", "chats with ananya on whatsapp.", "lives in indore.")
        problems = check_reading({"state": "done"}, digest, memories)
        self.assertIn("Ananya's fact saved as the user's memory (indore)", problems)
        self.assertIn("the person card has no engagement under relationship", problems)
        digest["person_card"] = {"relationship": [{"fact": "Engaged to Rohan."}]}
        self.assertEqual(check_reading({"state": "done"}, digest, memories), ["Ananya's fact saved as the user's memory (indore)"])


if __name__ == "__main__":
    unittest.main()
