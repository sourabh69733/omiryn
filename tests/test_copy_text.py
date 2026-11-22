"""Text Omi writes for the user to copy and send: one bubble as written, and never Omi's own talk."""

import unittest

from agent.context_engine.policy.replies import copy_pieces, outside_copy_text, own_words, split_assistant_reply
from agent.runtime.steps.checks import freshen_reply
from agent.runtime.steps.finish import finish_reply
from agent.runtime.steps.job import ReplyJob

MAIL = (
    "Subject: Re: Offer Letter\n\n"
    "Hi Priya,\n\n"
    "Thank you for the offer. I was expecting a CTC closer to 11 LPA. Is there flexibility to revisit the number?\n\n"
    "Thanks,\nAarav"
)
REPLY = f"Congrats! Ye lo draft:<next_message><copy>\n{MAIL}\n</copy><next_message>Tumhare paas doosra offer hai? Current salary kitni hai?"


def job(generate, question_limit=1) -> ReplyJob:
    return ReplyJob([{"role": "user", "content": "mail likh do"}], {}, generate, question_limit=question_limit)


class CopyTextTest(unittest.IsolatedAsyncioTestCase):
    def test_the_mail_is_one_bubble_without_the_tags(self) -> None:
        self.assertEqual(
            split_assistant_reply(REPLY),
            ["Congrats! Ye lo draft:", MAIL, "Tumhare paas doosra offer hai? Current salary kitni hai?"],
        )
        self.assertNotIn("copy>", finish_reply(REPLY, "mail likh do").text)

    def test_a_short_message_to_send_stays_whole_too(self) -> None:
        message = " ".join(["Hi bhaiya, ek referral chahiye tha."] * 8)
        self.assertEqual(split_assistant_reply(f"Ye bhej do: <copy>{message}</copy> Theek?"), ["Ye bhej do:", message, "Theek?"])

    def test_a_missing_closing_tag_ends_at_the_next_bubble(self) -> None:
        self.assertEqual(split_assistant_reply("Ye lo:<next_message>[copy]Hi Sir,\nI am Aarav.<next_message>Bhej do."), ["Ye lo:", "Hi Sir,\nI am Aarav.", "Bhej do."])

    def test_a_mail_spread_over_bubbles_inside_the_tags_is_one_text(self) -> None:
        pieces = copy_pieces("<copy>Hi Sir,<next_message>I am Aarav.</copy>")
        self.assertEqual(pieces, [("Hi Sir,\n\nI am Aarav.", True)])

    def test_own_words_leave_the_mail_out(self) -> None:
        self.assertEqual(own_words(REPLY), "Congrats! Ye lo draft:<next_message>Tumhare paas doosra offer hai? Current salary kitni hai?")
        self.assertEqual(own_words("haan bolo"), "haan bolo")

    def test_a_change_never_reaches_the_mail(self) -> None:
        changed = outside_copy_text(REPLY, lambda text: text.replace("?", "!"))
        self.assertIn(MAIL, changed)
        self.assertIn("doosra offer hai!", changed)
        self.assertEqual(outside_copy_text(REPLY, lambda text: "sab hata diya"), REPLY)

    async def test_a_question_inside_the_mail_is_not_omi_asking(self) -> None:
        async def never(*args, **kwargs):
            raise AssertionError("a reply with one own question needs no rewrite")

        reply = f"Ye lo:<next_message><copy>{MAIL}</copy><next_message>Bhej ke batana, theek?"
        self.assertEqual(await freshen_reply(reply, job(never)), (reply, None))

    async def test_extra_own_questions_are_trimmed_and_the_mail_is_not_rewritten(self) -> None:
        async def never(*args, **kwargs):
            raise AssertionError("a reply that carries text to copy is not rewritten")

        kept, info = await freshen_reply(REPLY, job(never))

        self.assertEqual(split_assistant_reply(kept)[1], MAIL)
        self.assertEqual(own_words(kept).count("?"), 1)
        self.assertEqual((info["rewritten"], info["kept_copy_text"], info["questions_trimmed"]), (False, True, True))


if __name__ == "__main__":
    unittest.main()
