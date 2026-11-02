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


class DescriptionTest(unittest.TestCase):
    def test_the_model_is_told_what_it_remembers_is_out_of_date(self) -> None:
        # Measured on Gemma 4 31B: a news request after earlier chat searched 4 of 12 times without
        # this, and 9 of 9 with it. Questions with no time in them still did not search.
        from agent.tools.web_search import DESCRIPTION

        self.assertIn("out of date", DESCRIPTION)
        self.assertIn("even if earlier replies in this chat did not", " ".join(DESCRIPTION.split()))

    def test_news_searches_are_told_to_ask_for_recent_dated_results(self) -> None:
        # Measured: without recent_days every search came back with old pages and no dates.
        from agent.tools.web_search import DESCRIPTION, PARAMETERS

        self.assertIn("set recent_days", " ".join(DESCRIPTION.split()))
        self.assertIn("no date", PARAMETERS["properties"]["recent_days"]["description"])


class NewsReplyTest(unittest.TestCase):
    def test_the_note_asks_for_real_items_with_source_and_date(self) -> None:
        note = web_note("ai news", [{"title": "T", "url": "https://x", "date": "", "text": "Y"}])
        self.assertIn("2-3 separate real items", note)
        self.assertIn("the source and its date", note)
        self.assertIn("do not call a page with no date new", note)

    def test_the_turn_is_told_about_search_only_when_it_is_on(self) -> None:
        from agent.context_engine.prompt_engine.blocks import _web_search_line

        with patch.dict("os.environ", {"TAVILY_API_KEY": "k", "AGENT_TOOLS": "true", "AGENT_WEB_SEARCH": "true"}):
            self.assertIn("call web_search", _web_search_line())
        with patch.dict("os.environ", {"TAVILY_API_KEY": ""}):
            self.assertEqual(_web_search_line(), "")
        with patch.dict("os.environ", {"TAVILY_API_KEY": "k", "AGENT_TOOLS": "false"}):
            self.assertEqual(_web_search_line(), "")

