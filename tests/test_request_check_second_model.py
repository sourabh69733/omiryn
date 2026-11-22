"""When the provider refuses the check model, a second model checks the reply instead of nobody."""

import os
import unittest
from unittest.mock import patch

from agent.providers.extraction import service
from agent.providers.shared.errors import AgentProviderError

FIRST, SECOND = "Qwen/Qwen3-235B-A22B-Instruct-2507", "meta-llama/Llama-3.3-70B-Instruct-Turbo"
NO_ENV = {"REQUEST_CHECK_MODEL": "", "REQUEST_CHECK_SECOND_MODEL": ""}


class RequestCheckSecondModelTest(unittest.IsolatedAsyncioTestCase):
    def test_the_models_in_order(self) -> None:
        with patch.dict(os.environ, NO_ENV):
            self.assertEqual(service.request_check_models("deepinfra"), [FIRST, SECOND])
        with patch.dict(os.environ, {**NO_ENV, "REQUEST_CHECK_SECOND_MODEL": "off"}):
            self.assertEqual(service.request_check_models("deepinfra"), [FIRST])

    async def test_a_refused_model_hands_over_to_the_second(self) -> None:
        tried: list[str] = []

        async def chat(**kwargs):
            tried.append(kwargs["model"])
            if kwargs["model"] == FIRST:
                raise AgentProviderError("deepinfra returned HTTP 429")
            return '{"broken": ["no questions"]}'

        with patch.dict(os.environ, NO_ENV), patch.object(service, "_provider_name", return_value="deepinfra"), patch.object(service, "provider_chat", chat):
            found = await service.check_reply_requests("draft", conversation_id="c1")

        self.assertEqual(tried, [FIRST, SECOND])
        self.assertEqual(found, {"broken": ["no questions"]})

    async def test_when_both_are_refused_the_error_reaches_the_caller(self) -> None:
        async def chat(**kwargs):
            raise AgentProviderError("deepinfra returned HTTP 429")

        with patch.dict(os.environ, NO_ENV), patch.object(service, "_provider_name", return_value="deepinfra"), patch.object(service, "provider_chat", chat):
            with self.assertRaises(AgentProviderError):
                await service.check_reply_requests("draft", conversation_id="c1")


if __name__ == "__main__":
    unittest.main()
