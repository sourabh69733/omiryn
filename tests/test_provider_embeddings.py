"""Tests the provider-neutral OpenAI-compatible embedding transport."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from agent.providers.gateway.embeddings import provider_embeddings


class ProviderEmbeddingsTest(unittest.IsolatedAsyncioTestCase):
    async def test_sends_batch_and_restores_provider_order(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["payload"] = __import__("json").loads(request.content)
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 1, "embedding": [0.0, 1.0]},
                        {"index": 0, "embedding": [1.0, 0.0]},
                    ],
                    "usage": {"prompt_tokens": 7, "total_tokens": 7},
                },
            )

        original_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            return original_client(
                transport=httpx.MockTransport(handler), timeout=kwargs["timeout"]
            )

        with (
            patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}),
            patch(
                "agent.providers.gateway.embeddings.httpx.AsyncClient",
                side_effect=client_factory,
            ),
            patch("agent.providers.gateway.embeddings._record_usage_event") as usage,
        ):
            vectors = await provider_embeddings(
                provider="deepinfra",
                model="embedding-model",
                inputs=["first", "second"],
                conversation_id="conversation-a",
            )

        self.assertEqual(vectors, [[1.0, 0.0], [0.0, 1.0]])
        self.assertEqual(captured["url"], "https://api.deepinfra.com/v1/openai/embeddings")
        self.assertEqual(captured["payload"], {
            "model": "embedding-model",
            "input": ["first", "second"],
        })
        self.assertTrue(usage.call_args.kwargs["success"])


if __name__ == "__main__":
    unittest.main()
