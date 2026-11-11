"""Omi never says which company or model made or runs it; a draft that does gets one rewrite."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from agent.context_engine.policy.identity import maker_claim
from agent.runtime.steps import REPLY_CHECKS
from agent.runtime.steps.checks import check_identity
from agent.runtime.steps.job import ReplyJob


class MakerClaimTest(unittest.TestCase):
    def test_finds_a_sentence_that_names_the_maker(self) -> None:
        for reply in (
            "I'm a large language model, trained by Google.",
            "Main Omi hoon. Mujhe Google ne banaya hai!",
            "I'm not made by Google, I'm made by the Omiryn team.",
            "Haan, main Gemma hoon.",
            "I am Gemini, your assistant.",
            "Main Google ka model hoon, par yahan Omi hoon.",
            "I am running on Llama under the hood.",
            "Honestly, I'm based on GPT-4.",
        ):
            self.assertIsNotNone(maker_claim(reply), reply)

    def test_leaves_other_mentions_alone(self) -> None:
        for reply in (
            "Omiryn made me, and I run on an AI model from another company.",
            "Your messages go through our server and an AI model, the same way ChatGPT works.",
            "Google Maps pe dekh lo, 10 min walk hai.",
            "Main ChatGPT jaisa nahi hoon, main tumhara dost hoon.",
            "Android was developed by Google in 2008.",
            "Tum Gemini ho? Isliye itne moody ho 😄",
            "",
        ):
            self.assertIsNone(maker_claim(reply), reply)


class IdentityCheckTest(unittest.TestCase):
    def _job(self, rewrite: str) -> tuple[ReplyJob, list]:
        notes: list = []

        async def generate(messages, **kwargs):
            notes.append(messages[-1]["content"])
            return rewrite

        return ReplyJob(reply_messages=[{"role": "user", "content": "who made you?"}], generation_arguments={}, generate=generate), notes

    def test_a_maker_claim_is_rewritten_once(self) -> None:
        job, notes = self._job("Omiryn made me. Underneath I run on an AI model from another company.")
        reply, info = asyncio.run(check_identity("I was developed by Google. Kya haal?", job))
        self.assertEqual(reply, "Omiryn made me. Underneath I run on an AI model from another company.")
        self.assertEqual(len(notes), 1)
        self.assertIn("without naming or ruling out any company or model", notes[0])
        self.assertEqual(info["quote"], "I was developed by Google.")
        self.assertFalse(info["still_claims"])

    def test_a_clean_reply_is_not_checked_by_a_model(self) -> None:
        job, notes = self._job("unused")
        self.assertEqual(asyncio.run(check_identity("Omiryn made me!", job)), ("Omiryn made me!", None))
        self.assertEqual(notes, [])

    def test_can_be_switched_off(self) -> None:
        job, notes = self._job("unused")
        with patch.dict("os.environ", {"AGENT_IDENTITY_CHECK": "false"}):
            reply, info = asyncio.run(check_identity("I was developed by Google.", job))
        self.assertEqual((reply, info, notes), ("I was developed by Google.", None, []))

    def test_runs_first_so_later_checks_read_the_fixed_text(self) -> None:
        self.assertEqual(REPLY_CHECKS[0][0], "identity_check")


if __name__ == "__main__":
    unittest.main()
