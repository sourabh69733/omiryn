"""find_places: on only with a key, sends only the query, and turns Google results into a short note."""

import json
import unittest
from unittest.mock import patch

import httpx

from agent.tools import ToolCall, ToolContext, run_calls, tool_specs
from agent.tools.places import places_note

CONTEXT = ToolContext("places-user", "omi")


def _client(handler):
    real = httpx.AsyncClient
    return lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs)


class PlacesToolTest(unittest.IsolatedAsyncioTestCase):
    def test_on_only_with_a_key(self) -> None:
        names = lambda: [spec["function"]["name"] for spec in tool_specs(CONTEXT)]
        with patch.dict("os.environ", {"GOOGLE_PLACES_API_KEY": ""}):
            self.assertNotIn("find_places", names())
        with patch.dict("os.environ", {"GOOGLE_PLACES_API_KEY": "k"}):
            self.assertIn("find_places", names())
        with patch.dict("os.environ", {"GOOGLE_PLACES_API_KEY": "k", "AGENT_PLACES": "false"}):
            self.assertNotIn("find_places", names())

    async def test_sends_the_query_and_returns_real_places(self) -> None:
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            seen["key"] = request.headers["x-goog-api-key"]
            seen["fields"] = request.headers["x-goog-fieldmask"]
            return httpx.Response(200, json={"places": [
                {
                    "displayName": {"text": "Third Wave Coffee"},
                    "primaryTypeDisplayName": {"text": "Coffee shop"},
                    "formattedAddress": "100 Feet Rd, Indiranagar, Bengaluru",
                    "rating": 4.4,
                    "userRatingCount": 2100,
                    "priceLevel": "PRICE_LEVEL_MODERATE",
                    "currentOpeningHours": {"openNow": True},
                    "regularOpeningHours": {"weekdayDescriptions": ["Monday: 8:00 AM – 11:00 PM"]},
                    "googleMapsUri": "https://maps.google.com/?cid=1",
                },
                {"displayName": {}},
            ]})

        with patch.dict("os.environ", {"GOOGLE_PLACES_API_KEY": "k"}), patch("agent.tools.places.httpx.AsyncClient", _client(handler)):
            [result] = await run_calls([ToolCall("find_places", {"query": "cafes in Indiranagar", "open_now": True, "min_rating": 4.2})], CONTEXT)

        self.assertEqual(seen["body"], {"textQuery": "cafes in Indiranagar", "pageSize": 5, "openNow": True, "minRating": 4.0})
        self.assertEqual(seen["key"], "k")
        self.assertIn("places.rating", seen["fields"])
        self.assertIn("Third Wave Coffee: Coffee shop, 4.4★ (2100 reviews), mid-range, open now.", result.note)
        self.assertIn("https://maps.google.com/?cid=1", result.note)
        self.assertIn("Monday: 8:00 AM", result.note)
        self.assertIn("cannot book", result.note)
        self.assertEqual((result.trace["ok"], result.trace["results"]), (True, 1))

    async def test_a_failing_lookup_tells_the_model_not_to_guess(self) -> None:
        with patch.dict("os.environ", {"GOOGLE_PLACES_API_KEY": "k"}), patch("agent.tools.places.httpx.AsyncClient", _client(lambda request: httpx.Response(403))):
            [result] = await run_calls([ToolCall("find_places", {"query": "x"})], CONTEXT)
        self.assertFalse(result.trace["ok"])
        self.assertIn("Do not guess", result.note)

    def test_nothing_found_is_said_plainly(self) -> None:
        self.assertIn("do not make places up", places_note("x", []))


if __name__ == "__main__":
    unittest.main()
