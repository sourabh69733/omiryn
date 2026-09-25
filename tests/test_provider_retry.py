import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from agent.memory_engine.memories.embeddings import embed_memory_query
from agent.providers.gateway.retry import post_with_retry

URL = "https://provider.test/v1/chat/completions"


def _client(outcomes: list) -> tuple[httpx.AsyncClient, list[int]]:
    """A client whose successive requests produce the given responses or errors."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        status, headers = outcome if isinstance(outcome, tuple) else (outcome, {})
        return httpx.Response(status, headers=headers, json={}, request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls


@patch("agent.providers.gateway.retry.asyncio.sleep", new_callable=AsyncMock)
class PostWithRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_connection_failure_is_retried(self, sleep: AsyncMock) -> None:
        client, calls = _client([httpx.ConnectTimeout("no route"), 200])
        async with client:
            response = await post_with_retry(client, URL, json={})
        self.assertEqual((response.status_code, len(calls)), (200, 2))
        sleep.assert_awaited_once_with(1.0)

    async def test_busy_provider_is_retried_honoring_short_retry_after(self, sleep: AsyncMock) -> None:
        client, calls = _client([(429, {"retry-after": "2"}), 200])
        async with client:
            response = await post_with_retry(client, URL, json={})
        self.assertEqual((response.status_code, len(calls)), (200, 2))
        sleep.assert_awaited_once_with(2.0)

    async def test_gives_up_after_two_retries_and_returns_last_response(self, sleep: AsyncMock) -> None:
        client, calls = _client([503, 503, 503])
        async with client:
            response = await post_with_retry(client, URL, json={})
        self.assertEqual((response.status_code, len(calls)), (503, 3))
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [1.0, 3.0])

    async def test_client_errors_and_slow_responses_are_not_retried(self, sleep: AsyncMock) -> None:
        client, calls = _client([400])
        async with client:
            response = await post_with_retry(client, URL, json={})
        self.assertEqual((response.status_code, len(calls)), (400, 1))

        client, calls = _client([httpx.ReadTimeout("slow")])
        async with client:
            with self.assertRaises(httpx.ReadTimeout):
                await post_with_retry(client, URL, json={})
        self.assertEqual(len(calls), 1)
        sleep.assert_not_awaited()

    async def test_retries_can_be_switched_off(self, sleep: AsyncMock) -> None:
        client, calls = _client([503])
        with patch.dict(os.environ, {"AGENT_PROVIDER_RETRIES": "0"}):
            async with client:
                response = await post_with_retry(client, URL, json={})
        self.assertEqual((response.status_code, len(calls)), (503, 1))


class QueryEmbeddingTimeoutTest(unittest.IsolatedAsyncioTestCase):
    async def test_reply_time_query_uses_a_short_timeout(self) -> None:
        embeddings = AsyncMock(return_value=[[0.1, 0.2]])
        env = {"MEMORY_EMBEDDING_MODEL": "deepinfra:BAAI/bge-m3"}
        with patch.dict(os.environ, env), patch(
            "agent.memory_engine.memories.embeddings.provider_embeddings", new=embeddings
        ):
            result = await embed_memory_query("how did the interview go?")
        self.assertEqual(result["dimensions"], 2)
        self.assertEqual(embeddings.await_args.kwargs["timeout_seconds"], 8.0)


if __name__ == "__main__":
    unittest.main()
