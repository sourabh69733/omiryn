"""Consent for private areas in matching: off until the user allows it, kept across card writes."""

import unittest

from fastapi.testclient import TestClient

from storage import get_vibe_card, private_matching_allowed, reset_db, set_vibe_intro, update_vibe_card

USER_ID = "consent-user"


def line(text: str) -> dict:
    return {"text": text, "evidence": [{"conversation_id": "c1", "message_index": 0, "sent_at": "2026-09-10T10:00:00+00:00"}]}


class PrivateConsentTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        from api.main import app
        from security.auth import CurrentUser, require_user

        app.dependency_overrides[require_user] = lambda: CurrentUser(id=USER_ID, email="consent@example.com", display_name="Riya")
        self.app = app
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()

    def test_never_asked_counts_as_no(self) -> None:
        body = self.client.get("/api/me/consent").json()

        self.assertEqual(body, {"private_matching": False, "asked": False, "at": None})
        self.assertFalse(private_matching_allowed(get_vibe_card(USER_ID)))

    def test_allow_then_stop(self) -> None:
        allowed = self.client.put("/api/me/consent", json={"private_matching": True}).json()
        self.assertTrue(allowed["private_matching"])
        self.assertTrue(allowed["asked"])
        self.assertTrue(private_matching_allowed(get_vibe_card(USER_ID)))

        stopped = self.client.put("/api/me/consent", json={"private_matching": False}).json()
        self.assertFalse(stopped["private_matching"])
        self.assertEqual(self.client.get("/api/me/consent").json()["asked"], True)
        self.assertFalse(private_matching_allowed(get_vibe_card(USER_ID)))

    def test_consent_survives_line_and_intro_writes(self) -> None:
        self.client.put("/api/me/consent", json={"private_matching": True})

        update_vibe_card(USER_ID, {"values": line("Believes in honesty.")})
        set_vibe_intro(USER_ID, {"text": "Laughs at puns.", "chips": []})
        update_vibe_card(USER_ID, {}, reject=("values",))

        card = get_vibe_card(USER_ID)
        self.assertTrue(private_matching_allowed(card))
        self.assertEqual(card["intro"]["text"], "Laughs at puns.")

    def test_vibe_page_carries_the_choice(self) -> None:
        self.assertEqual(self.client.get("/api/me/vibe").json()["consent"]["asked"], False)

        self.client.put("/api/me/consent", json={"private_matching": True})

        self.assertTrue(self.client.get("/api/me/vibe").json()["consent"]["private_matching"])


if __name__ == "__main__":
    unittest.main()
