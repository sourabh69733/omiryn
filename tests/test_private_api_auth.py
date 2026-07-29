import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app
from storage import reset_db


class PrivateApiAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        reset_db()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_private_apis_reject_anonymous_even_when_auth_required_is_false(self) -> None:
        with patch.dict(os.environ, {"AUTH_REQUIRED": "false"}):
            responses = [
                self.client.post("/api/agent/conversations"),
                self.client.get("/api/agent/conversations"),
                self.client.post("/api/agent-submissions/profile", json={}),
                self.client.get("/api/agent/usage"),
                self.client.get("/api/me/profile"),
            ]

        self.assertTrue(responses)
        for response in responses:
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["detail"], "Sign in to continue.")

    def test_public_helper_routes_remain_anonymous(self) -> None:
        with patch.dict(os.environ, {"AUTH_REQUIRED": "false"}):
            response = self.client.get("/api/context-import-prompt")

        self.assertEqual(response.status_code, 200)
        self.assertIn("prompt", response.json())

