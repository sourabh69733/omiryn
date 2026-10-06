"""Health shows which agent pipeline and prompt the server is running."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


class HealthTest(unittest.TestCase):
    def setUp(self) -> None:
        from api.main import app

        self.client = TestClient(app)

    def test_reports_pipeline_and_prompt_version(self) -> None:
        with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "AGENT_BEHAVIOR_VERSION": "v3-1"}):
            body = self.client.get("/health").json()

        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["pipeline"], {"version": "v3", "memory_contract": 3})
        self.assertEqual(body["prompt_version"], "v3-1")

    def test_a_v2_deploy_and_an_archived_prompt_are_visible(self) -> None:
        with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v2", "AGENT_BEHAVIOR_VERSION": "v1"}):
            body = self.client.get("/health").json()

        self.assertEqual(body["pipeline"]["version"], "v2")
        self.assertEqual(body["prompt_version"], "v4")

    def test_a_bad_setting_is_reported_not_crashed(self) -> None:
        with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v9"}):
            response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertIn("AGENT_PIPELINE_VERSION", response.json()["pipeline"]["error"])


if __name__ == "__main__":
    unittest.main()
