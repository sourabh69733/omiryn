"""The made-up people for the judge evaluation come in friend pairs and never name each other."""

import unittest

from agent.evals.matching.personas import KNOWN_FRIEND_PAIRS, MATCH_PERSONAS, persona_by_id


class MatchPersonasTest(unittest.TestCase):
    def test_every_person_has_one_friend_who_names_them_back(self) -> None:
        ids = [person.id for person in MATCH_PERSONAS]
        self.assertEqual(len(ids), len(set(ids)))
        for person in MATCH_PERSONAS:
            self.assertNotEqual(person.friend, person.id)
            self.assertEqual(persona_by_id(person.friend).friend, person.id)
        self.assertEqual(len(KNOWN_FRIEND_PAIRS), len(MATCH_PERSONAS) // 2)

    def test_nobody_mentions_their_friend_or_the_matching(self) -> None:
        names = {person.id: person.name for person in MATCH_PERSONAS}
        for person in MATCH_PERSONAS:
            text = person.persona.casefold()
            self.assertNotIn(names[person.friend].casefold(), text)
            self.assertNotIn("matching", text)
            self.assertNotIn("matched", text)


if __name__ == "__main__":
    unittest.main()
