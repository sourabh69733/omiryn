"""Picking the reply model in Profile > Advanced: only offered models, used for replies."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.providers.shared.model_catalog import preferred_reply_model
from api.main import app, current_user
from security.auth import CurrentUser
from storage import reset_db

USER_ID = "model-user"
RUNTIME = {
    "provider": "deepinfra",
    "model": "mistralai/Mistral-Small-3.2-24B-Instruct-2506",
    "available_models": ["mistralai/Mistral-Small-3.2-24B-Instruct-2506", "google/gemma-4-31B-it", "acme/new-model"],
}


class ReplyModelChoiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"AUTH_REQUIRED": "false"})
        self.env.start()
        self.runtime = patch("agent.providers.shared.model_catalog.agent_runtime_status", return_value=RUNTIME)
        self.runtime.start()

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id=USER_ID, email="m@example.com", display_name="M")

        app.dependency_overrides[current_user] = signed_in_user
        reset_db()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.runtime.stop()
        self.env.stop()

    def test_the_picker_lists_offered_models_with_their_strong_point(self) -> None:
        data = self.client.get("/api/agent/settings/model").json()

        self.assertIsNone(data["selected"])
        self.assertEqual(data["default"], RUNTIME["model"])
        names = {choice["id"]: (choice["name"], choice["strength"]) for choice in data["choices"]}
        self.assertEqual(names["google/gemma-4-31B-it"], ("Gemma", "warm, longer replies"))
        # A model without a label still shows, named by its ID.
        self.assertEqual(names["acme/new-model"], ("new-model", ""))

    def test_a_pick_is_saved_and_used_for_replies(self) -> None:
        self.client.put("/api/agent/settings/model", json={"model": "google/gemma-4-31B-it"})

        self.assertEqual(self.client.get("/api/agent/settings/model").json()["selected"], "google/gemma-4-31B-it")
        self.assertEqual(preferred_reply_model(USER_ID, "chat-model"), "google/gemma-4-31B-it")

    def test_back_to_default_and_unknown_models(self) -> None:
        self.assertEqual(self.client.put("/api/agent/settings/model", json={"model": "made/up"}).status_code, 400)
        self.client.put("/api/agent/settings/model", json={"model": "google/gemma-4-31B-it"})
        self.client.put("/api/agent/settings/model", json={"model": None})
        self.assertEqual(preferred_reply_model(USER_ID, "chat-model"), "chat-model")


if __name__ == "__main__":
    unittest.main()
