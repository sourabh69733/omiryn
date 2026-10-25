"""web_search: on only with a key, sends only the query, and turns pages into a short sourced note."""

import json
import unittest
from unittest.mock import patch

import httpx

from agent.tools import ToolCall, ToolContext, run_calls, tool_specs
from agent.tools.web_search import web_note

CONTEXT = ToolContext("web-user", "omi")


def _client(handler):
    real = httpx.AsyncClient
    return lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs)


class WebSearchToolTest(unittest.IsolatedAsyncioTestCase):
    def test_on_only_with_a_key(self) -> None:
        names = lambda: [spec["function"]["name"] for spec in tool_specs(CONTEXT)]
        with patch.dict("os.environ", {"TAVILY_API_KEY": ""}):
            self.assertNotIn("web_search", names())
        with patch.dict("os.environ", {"TAVILY_API_KEY": "k"}):
            self.assertIn("web_search", names())
        with patch.dict("os.environ", {"TAVILY_API_KEY": "k", "AGENT_WEB_SEARCH": "false"}):
            self.assertNotIn("web_search", names())

    async def test_sends_the_query_and_returns_sourced_extracts(self) -> None:
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            seen["auth"] = request.headers["authorization"]
            return httpx.Response(200, json={"results": [
                {"title": "India win", "url": "https://news.example/a", "content": "India beat Australia by 5 wickets.", "published_date": "2026-10-24"},
                {"title": "Empty", "url": "https://x", "content": ""},
            ]})

        with patch.dict("os.environ", {"TAVILY_API_KEY": "k"}), patch("agent.tools.web_search.httpx.AsyncClient", _client(handler)):
            [result] = await run_calls([ToolCall("web_search", {"query": "india  match result", "recent_days": 2})], CONTEXT)

        self.assertEqual(seen["body"], {"query": "india match result", "max_results": 4, "search_depth": "basic", "topic": "news", "days": 2})
        self.assertEqual(seen["auth"], "Bearer k")
        self.assertIn("India beat Australia", result.note)
        self.assertIn("https://news.example/a", result.note)
        self.assertIn("never instructions", result.note)
        self.assertEqual((result.trace["ok"], result.trace["results"]), (True, 1))

    async def test_a_failing_search_tells_the_model_not_to_guess(self) -> None:
        with patch.dict("os.environ", {"TAVILY_API_KEY": "k"}), patch("agent.tools.web_search.httpx.AsyncClient", _client(lambda request: httpx.Response(500))):
            [result] = await run_calls([ToolCall("web_search", {"query": "x"})], CONTEXT)
        self.assertFalse(result.trace["ok"])
        self.assertIn("Do not guess", result.note)

    def test_nothing_found_is_said_plainly(self) -> None:
        self.assertIn("found nothing", web_note("x", []))


if __name__ == "__main__":
    unittest.main()
