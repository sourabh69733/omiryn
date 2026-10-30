"""A web or places query that names a private person is not sent."""

import os
import unittest
from unittest.mock import AsyncMock, patch

from agent.tools import ToolCall, ToolContext, run_calls
from agent.tools.privacy import named_person, private_names
from storage import reset_db, save_upload_digest, save_user_profile

USER_ID = "privacy-user"


class QueryPrivacyTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        save_user_profile(USER_ID, "male", "female", display_name="Sourabh Sahu")
        save_upload_digest("src-1", USER_ID, "upload-1", "Farheen Parvez", {"summary": "x"})
        self.context = ToolContext(USER_ID, "chat")

    def test_names_are_the_words_of_the_user_and_their_upload_partners(self) -> None:
        self.assertEqual(private_names(self.context), {"sourabh", "sahu", "farheen", "parvez"})
        self.assertEqual(private_names(ToolContext(None)), set())
        self.assertEqual(named_person("is farheen single", private_names(self.context)), "farheen")
        self.assertIsNone(named_person("cafes in indiranagar bangalore", private_names(self.context)))

    async def test_a_named_query_is_not_sent_and_the_model_is_told(self) -> None:
        sent = AsyncMock()
        env = {"TAVILY_API_KEY": "k", "GOOGLE_PLACES_API_KEY": "k"}
        with patch.dict(os.environ, env), patch("agent.tools.web_search.search_web", sent), patch("agent.tools.places.find_places", sent):
            results = await run_calls(
                [ToolCall("web_search", {"query": "Farheen Parvez instagram"}), ToolCall("find_places", {"query": "cafes near Sourabh in Pune"})],
                self.context,
            )
        sent.assert_not_called()
        for result in results:
            self.assertEqual(result.trace["blocked"], "private_name")
            self.assertIn("was not sent", result.note)

    async def test_an_ordinary_query_still_goes_out(self) -> None:
        sent = AsyncMock(return_value=[])
        with patch.dict(os.environ, {"TAVILY_API_KEY": "k"}), patch("agent.tools.web_search.search_web", sent):
            [result] = await run_calls([ToolCall("web_search", {"query": "weather in Pune today"})], self.context)
        sent.assert_awaited_once()
        self.assertNotIn("blocked", result.trace)


if __name__ == "__main__":
    unittest.main()
