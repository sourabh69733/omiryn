"""Person cards: facts about the other person by kind, each with the real line it came from."""

import unittest
from zoneinfo import ZoneInfo

from agent.cognition.background.person_card import checked_facts, merge_facts
from agent.context_engine.assembly.uploaded_chats import person_card_lines

ZONE = ZoneInfo("Asia/Kolkata")
MESSAGES = [
    {"role": "other", "speaker": "Farheen", "content": "Hm.. i might get engaged this year", "created_at": "2026-10-08T16:34:00+00:00"},
    {"role": "user", "content": "Ohh, u have guy?", "created_at": "2026-10-08T16:35:00+00:00"},
    {"role": "other", "speaker": "Farheen", "content": "Decided to do engagement I asked for another year", "created_at": "2026-10-08T16:36:00+00:00"},
]


class PersonCardTest(unittest.TestCase):
    def test_quotes_come_from_the_chat_not_the_model(self) -> None:
        raw = {"facts": [
            {"category": "relationship", "fact": "Decided to get engaged; marriage after a year.", "line": 2},
            {"category": "relationship", "fact": "Is a pilot.", "line": 99},
            {"category": "astrology", "fact": "Is a Leo.", "line": 0},
        ]}
        [fact] = checked_facts(raw, MESSAGES, range(0, 3), "Farheen", ZONE)
        self.assertEqual((fact["quote"], fact["speaker"], fact["date"]), ("Decided to do engagement I asked for another year", "Farheen", "2026-10-08"))

    def test_newest_first_and_no_repeats(self) -> None:
        facts = [
            {"category": "relationship", "fact": "Might get engaged this year.", "line": 0, "date": "2026-10-08", "speaker": "Farheen", "quote": "a"},
            {"category": "relationship", "fact": "Decided to get engaged.", "line": 2, "date": "2026-10-08", "speaker": "Farheen", "quote": "b"},
            {"category": "relationship", "fact": "Decided to get engaged!", "line": 2, "date": "2026-10-08", "speaker": "Farheen", "quote": "b"},
        ]
        card = merge_facts(facts)
        self.assertEqual([fact["fact"] for fact in card["relationship"]], ["Decided to get engaged.", "Might get engaged this year."])

    def test_reply_sees_facts_with_their_lines_and_the_rule(self) -> None:
        card = {"relationship": [{"fact": "Decided to get engaged.", "date": "2026-10-08", "speaker": "Farheen", "quote": "Decided to do engagement"}]}
        text = "\n".join(person_card_lines(card, "Farheen"))
        self.assertIn('Relationship: Decided to get engaged. [2026-10-08, Farheen: "Decided to do engagement"]', text)
        self.assertIn("anything not here, say you don't know", text)


if __name__ == "__main__":
    unittest.main()
