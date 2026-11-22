"""The line breaks the model writes inside a bubble reach the user: steps and a mail keep their lines."""

import unittest

from agent.context_engine.policy.freshness import trim_questions
from agent.context_engine.policy.replies import REPLY_PART_WORD_LIMIT, split_assistant_reply, tidy_lines
from agent.context_engine.prompt_engine.modules.output_format import output_format_prompt
from agent.providers.shared.messages import _compact_chat_reply

ASKED = [{"role": "user", "content": "offer aaya hai 9 lpa, 11 kaise maangu, mail likh do"}]
MAIL = (
    "Subject: Re: Offer Letter\n\n"
    "Hi Priya,\n\n"
    "Thank you so much for the offer. I'm really excited about the role and the team, and I'd love to make this work.\n\n"
    "Based on my skills and the responsibilities of the role, I was expecting a CTC closer to 11 LPA.\n\n"
    "Thanks again,\nAarav"
)
RAW = f"Congrats! Ye lo draft:\n<next_message>\n{MAIL}\n\n<next_message>\nTip: ek aur offer ho to mail mein likh do."


class ReplyLinesTest(unittest.TestCase):
    def test_a_drafted_mail_keeps_its_lines_and_stays_one_bubble(self) -> None:
        parts = split_assistant_reply(_compact_chat_reply(RAW, ASKED))

        self.assertEqual(parts, ["Congrats! Ye lo draft:", MAIL, "Tip: ek aur offer ho to mail mein likh do."])
        self.assertGreater(len(MAIL.split()), REPLY_PART_WORD_LIMIT)

    def test_steps_keep_one_line_each(self) -> None:
        steps = "1. UAN portal par login karo.\n2. UMANG app mein Raise Claim kholo."
        self.assertEqual(split_assistant_reply(_compact_chat_reply(f"Do tarike hain:\n{steps}", ASKED)), [f"Do tarike hain:\n{steps}"])

    def test_in_a_reply_written_as_one_message_an_empty_line_starts_a_new_bubble(self) -> None:
        steps = "1. UAN portal par login karo.\n2. UMANG app mein Raise Claim kholo."
        reply = f"Do tarike hain:\n\n{steps}\n\nJob chhod di hai ya soch rahe ho?"
        self.assertEqual(split_assistant_reply(_compact_chat_reply(reply, ASKED)), ["Do tarike hain:", steps, "Job chhod di hai ya soch rahe ho?"])

    def test_with_separators_an_empty_line_stays_inside_the_bubble(self) -> None:
        first = "Do tarike hain:\n\n1. UAN portal.\n2. UMANG app."
        self.assertEqual(split_assistant_reply(f"{first}<next_message>Job chhod di hai?"), [first, "Job chhod di hai?"])

    def test_too_many_paragraphs_stay_together_instead_of_being_dropped(self) -> None:
        reply = "\n\n".join(f"Baat number {index} ye hai." for index in range(1, 10))
        self.assertEqual(split_assistant_reply(reply), [reply])

    def test_spaces_and_extra_empty_lines_are_tidied(self) -> None:
        self.assertEqual(tidy_lines("  haan   yaar \r\n\n\n\n  theek   hai  \n"), "haan yaar\n\ntheek hai")

    def test_markdown_bold_is_shown_as_plain_text(self) -> None:
        self.assertEqual(split_assistant_reply("1. **UAN portal** par login karo."), ["1. UAN portal par login karo."])
        self.assertEqual(tidy_lines("2 ** 3 is 8"), "2 ** 3 is 8")

    def test_a_reply_on_one_line_is_unchanged(self) -> None:
        text = "haan yaar, ye sahi lag raha hai. kal milte hain?"
        self.assertEqual(_compact_chat_reply(text, ASKED), text)
        self.assertEqual(split_assistant_reply(text), [text])

    def test_a_long_part_without_line_breaks_is_still_split_at_sentence_ends(self) -> None:
        sentence = "Ye ek seedha sa vaakya hai jo kaafi lamba chalta hai aur phir khatam hota hai."
        parts = split_assistant_reply(" ".join([sentence] * 4))

        self.assertEqual(parts, [f"{sentence} {sentence}", f"{sentence} {sentence}"])

    def test_trimming_questions_keeps_the_lines(self) -> None:
        reply = "Do kaam karo:\n1. Resume bhejo.\n2. Call karo.\nKab bhejoge? Kis ko bhejoge?"
        self.assertEqual(trim_questions(reply, 1), "Do kaam karo:\n1. Resume bhejo.\n2. Call karo.\nKis ko bhejoge?")

    def test_the_prompt_says_how_to_lay_out_steps_and_drafts(self) -> None:
        prompt = output_format_prompt()
        self.assertIn("Line breaks inside a bubble are shown", prompt)
        self.assertIn("goes between <copy> and", prompt)


if __name__ == "__main__":
    unittest.main()
