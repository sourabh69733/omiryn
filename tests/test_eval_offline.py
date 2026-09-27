import os
import unittest
from unittest.mock import patch

from agent.evals.shared.offline import keep_mock_runs_offline


class KeepMockRunsOfflineTest(unittest.TestCase):
    def test_mock_runs_turn_off_embeddings_even_when_env_sets_a_model(self) -> None:
        with patch.dict(os.environ, {"MEMORY_EMBEDDING_MODEL": "deepinfra:BAAI/bge-m3"}):
            keep_mock_runs_offline("mock")
            self.assertEqual(os.environ["MEMORY_EMBEDDING_MODEL"], "off")

    def test_real_providers_keep_their_embeddings(self) -> None:
        with patch.dict(os.environ, {"MEMORY_EMBEDDING_MODEL": "deepinfra:BAAI/bge-m3"}):
            keep_mock_runs_offline("deepinfra")
            self.assertEqual(os.environ["MEMORY_EMBEDDING_MODEL"], "deepinfra:BAAI/bge-m3")


if __name__ == "__main__":
    unittest.main()
