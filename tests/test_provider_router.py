from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from agent.evals.behavior.judge import _provider_call as judge_provider_call
from agent.evals.behavior.simulated_user import _provider_call as simulated_user_provider_call
from agent.runtime.providers.chat import generate_agent_reply
from agent.runtime.providers.clients import _openai_compatible_chat
from agent.runtime.providers.registry import (
    EVAL_PROVIDER_NAMES,
    OPENAI_COMPATIBLE_PROVIDERS,
    PROVIDER_REGISTRY,
    PROVIDER_NAMES,
    ProviderSpec,
    provider_model,
)
from agent.runtime.providers.errors import AgentProviderError
from agent.runtime.providers.extraction import extract_profile
from agent.runtime.providers.router import provider_chat


class ProviderRouterTest(unittest.IsolatedAsyncioTestCase):
    async def test_routes_openai_compatible_provider_with_all_request_fields(self) -> None:
        with patch(
            "agent.runtime.providers.router._openai_compatible_chat",
            new_callable=AsyncMock,
            return_value="reply",
        ) as call:
            result = await provider_chat(
                provider=" DeepInfra ",
                system_prompt="system",
                messages=[{"role": "user", "content": "hello"}],
                temperature=0.7,
                conversation_id="conversation",
                request_kind="test_kind",
                model="model-a",
                timeout_seconds=91,
                response_format={"type": "json_object"},
                tools=[{"type": "function"}],
                tool_choice="required",
            )

        self.assertEqual(result, "reply")
        call.assert_awaited_once_with(
            "deepinfra",
            "system",
            [{"role": "user", "content": "hello"}],
            timeout_seconds=91,
            temperature=0.7,
            conversation_id="conversation",
            request_kind="test_kind",
            model="model-a",
            response_format={"type": "json_object"},
            tools=[{"type": "function"}],
            tool_choice="required",
        )

    async def test_routes_groq_without_changing_request_fields(self) -> None:
        with patch(
            "agent.runtime.providers.router._groq_chat",
            new_callable=AsyncMock,
            return_value="reply",
        ) as call:
            await provider_chat(
                provider="groq",
                system_prompt="system",
                messages=[],
                timeout_seconds=75,
            )

        call.assert_awaited_once_with(
            "system",
            [],
            timeout_seconds=75,
            temperature=0.4,
            conversation_id=None,
            request_kind="chat_reply",
            model=None,
            tools=None,
            tool_choice=None,
        )

    async def test_routes_ollama_without_unsupported_timeout_argument(self) -> None:
        with patch(
            "agent.runtime.providers.router._ollama_chat",
            new_callable=AsyncMock,
            return_value="reply",
        ) as call:
            await provider_chat(
                provider="ollama",
                system_prompt="system",
                messages=[],
                timeout_seconds=75,
            )

        self.assertNotIn("timeout_seconds", call.await_args.kwargs)

    async def test_mock_and_unknown_providers_fail_at_generic_transport_layer(self) -> None:
        for provider in ("mock", "unknown", ""):
            with self.subTest(provider=provider), self.assertRaises(AgentProviderError):
                await provider_chat(provider=provider, system_prompt="system", messages=[])

    def test_provider_names_have_one_shared_source(self) -> None:
        self.assertEqual(
            PROVIDER_NAMES,
            ("openai", "deepinfra", "fireworks", "groq", "ollama", "mock"),
        )
        self.assertEqual(
            EVAL_PROVIDER_NAMES,
            ("openai", "deepinfra", "fireworks", "groq", "mock"),
        )
        self.assertEqual(
            OPENAI_COMPATIBLE_PROVIDERS,
            {"openai", "deepinfra", "fireworks"},
        )
        self.assertEqual(PROVIDER_NAMES, tuple(PROVIDER_REGISTRY))

    def test_openai_registry_entry_uses_standard_api_configuration(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "test-openai-key",
                "OPENAI_MODEL": "gpt-test-model",
            },
        ):
            from agent.runtime.providers.clients import _openai_compatible_provider_config

            config = _openai_compatible_provider_config("openai", None)

        self.assertEqual(config["api_key"], "test-openai-key")
        self.assertEqual(config["model"], "gpt-test-model")
        self.assertEqual(config["chat_url"], "https://api.openai.com/v1/chat/completions")

    async def test_openai_request_uses_key_model_and_chat_completions_endpoint(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["authorization"] = request.headers.get("Authorization")
            captured["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "OpenAI reply"}}],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 3,
                        "total_tokens": 13,
                    },
                },
            )

        original_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            return original_client(
                transport=httpx.MockTransport(handler), timeout=kwargs["timeout"]
            )

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-openai-key"}),
            patch(
                "agent.runtime.providers.clients.httpx.AsyncClient",
                side_effect=client_factory,
            ),
            patch("agent.runtime.providers.clients._record_usage_event") as usage,
        ):
            result = await _openai_compatible_chat(
                "openai",
                "system prompt",
                [{"role": "user", "content": "hello"}],
                model="gpt-test-model",
                request_kind="behavior_eval_user_judge",
            )

        self.assertEqual(result, "OpenAI reply")
        self.assertEqual(captured["url"], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(captured["authorization"], "Bearer test-openai-key")
        self.assertEqual(captured["payload"]["model"], "gpt-test-model")
        self.assertEqual(captured["payload"]["messages"][0]["role"], "system")
        self.assertEqual(usage.call_args.kwargs["provider"], "openai")

    async def test_openai_compatible_request_can_use_json_response_format(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": '{"reply":"ok","data_points":[]}'}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
                },
            )

        original_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            return original_client(
                transport=httpx.MockTransport(handler), timeout=kwargs["timeout"]
            )

        with (
            patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}),
            patch("agent.runtime.providers.clients.httpx.AsyncClient", side_effect=client_factory),
            patch("agent.runtime.providers.clients._record_usage_event"),
        ):
            result = await _openai_compatible_chat(
                "deepinfra",
                "system prompt",
                [{"role": "user", "content": "hello"}],
                response_format={"type": "json_object"},
            )

        self.assertEqual(result, '{"reply":"ok","data_points":[]}')
        self.assertEqual(captured["payload"]["response_format"], {"type": "json_object"})

    async def test_json_schema_response_bypasses_plain_chat_compaction(self) -> None:
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "turn_output",
                "schema": {"type": "object"},
            },
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": '{"reply":"ok","data_points":[]}'}}],
                    "usage": {},
                },
            )

        original_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            return original_client(
                transport=httpx.MockTransport(handler), timeout=kwargs["timeout"]
            )

        with (
            patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}),
            patch("agent.runtime.providers.clients.httpx.AsyncClient", side_effect=client_factory),
            patch("agent.runtime.providers.clients._record_usage_event"),
            patch(
                "agent.runtime.providers.clients._compact_chat_reply",
                side_effect=AssertionError("structured output must not be compacted"),
            ),
        ):
            result = await _openai_compatible_chat(
                "deepinfra",
                "system prompt",
                [{"role": "user", "content": "hello"}],
                request_kind="chat_reply",
                response_format=response_format,
            )

        self.assertEqual(result, '{"reply":"ok","data_points":[]}')

    async def test_forced_tool_call_returns_arguments_without_chat_compaction(self) -> None:
        captured: dict = {}
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "return_companion_response",
                    "parameters": {"type": "object"},
                },
            }
        ]
        tool_choice = {
            "type": "function",
            "function": {"name": "return_companion_response"},
        }
        arguments = '{"reply":"Visible reply","data_points":[]}'

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "type": "function",
                                        "function": {
                                            "name": "return_companion_response",
                                            "arguments": arguments,
                                        },
                                    }
                                ],
                            }
                        }
                    ],
                    "usage": {},
                },
            )

        original_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            return original_client(
                transport=httpx.MockTransport(handler), timeout=kwargs["timeout"]
            )

        with (
            patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"}),
            patch("agent.runtime.providers.clients.httpx.AsyncClient", side_effect=client_factory),
            patch("agent.runtime.providers.clients._record_usage_event"),
            patch(
                "agent.runtime.providers.clients._compact_chat_reply",
                side_effect=AssertionError("tool arguments must not be compacted"),
            ),
        ):
            result = await _openai_compatible_chat(
                "deepinfra",
                "normal companion prompt",
                [{"role": "user", "content": "hello"}],
                tools=tools,
                tool_choice=tool_choice,
            )

        self.assertEqual(result, arguments)
        self.assertEqual(captured["payload"]["tools"], tools)
        self.assertEqual(captured["payload"]["tool_choice"], tool_choice)
        self.assertNotIn("response_format", captured["payload"])

    async def test_one_compatible_registry_entry_is_enough_for_shared_routing(self) -> None:
        spec = ProviderSpec(
            name="future-provider",
            transport="openai_compatible",
            api_key_envs=("FUTURE_API_KEY",),
            model_env="FUTURE_MODEL",
            default_model="future-model",
            available_models_env="FUTURE_AVAILABLE_MODELS",
            default_available_models=("future-model",),
            base_url_env="FUTURE_BASE_URL",
            default_base_url="https://future.invalid/v1",
        )
        with (
            patch.dict(PROVIDER_REGISTRY, {"future-provider": spec}),
            patch(
                "agent.runtime.providers.router._openai_compatible_chat",
                new_callable=AsyncMock,
                return_value="future reply",
            ) as call,
        ):
            result = await provider_chat(
                provider="future-provider",
                system_prompt="system",
                messages=[],
            )
            model = provider_model("future-provider")

        self.assertEqual(result, "future reply")
        self.assertEqual(model, "future-model")
        self.assertEqual(call.await_args.args[0], "future-provider")


class ProviderRoleReuseTest(unittest.IsolatedAsyncioTestCase):
    async def test_companion_preserves_its_behavior_and_uses_shared_router(self) -> None:
        with (
            patch.dict("os.environ", {"AGENT_PROVIDER": "deepinfra"}),
            patch(
                "agent.runtime.providers.chat.provider_chat",
                new_callable=AsyncMock,
                return_value="companion reply",
            ) as call,
        ):
            result = await generate_agent_reply(
                [{"role": "user", "content": "Tell me honestly what you think."}],
                conversation_id="conversation",
                model="companion-model",
                system_prompt="existing companion prompt",
            )

        self.assertEqual(result, "companion reply")
        self.assertEqual(call.await_args.kwargs["provider"], "deepinfra")
        self.assertEqual(call.await_args.kwargs["system_prompt"], "existing companion prompt")
        self.assertEqual(call.await_args.kwargs["model"], "companion-model")
        self.assertEqual(call.await_args.kwargs["request_kind"], "chat_reply")

    async def test_extraction_uses_same_router_with_extraction_role(self) -> None:
        with (
            patch.dict("os.environ", {"AGENT_PROVIDER": "fireworks"}),
            patch(
                "agent.runtime.providers.extraction.provider_chat",
                new_callable=AsyncMock,
                return_value='{"display_name":"Aarav"}',
            ) as call,
        ):
            result = await extract_profile(
                [{"role": "user", "content": "My name is Aarav."}],
                conversation_id="conversation",
            )

        self.assertEqual(result["display_name"], "Aarav")
        self.assertEqual(call.await_args.kwargs["provider"], "fireworks")
        self.assertEqual(call.await_args.kwargs["temperature"], 0)
        self.assertEqual(call.await_args.kwargs["request_kind"], "profile_extract")

    async def test_judge_and_ai_user_wrappers_share_the_router(self) -> None:
        for module, factory, request_kind in (
            (
                "agent.evals.behavior.judge.provider_chat",
                judge_provider_call,
                "behavior_eval_judge",
            ),
            (
                "agent.evals.behavior.simulated_user.provider_chat",
                simulated_user_provider_call,
                "behavior_eval_user_simulator",
            ),
        ):
            with (
                self.subTest(module=module),
                patch(
                    module,
                    new_callable=AsyncMock,
                    return_value="response",
                ) as call,
            ):
                result = await factory("groq")(
                    "system",
                    [{"role": "user", "content": "payload"}],
                    request_kind=request_kind,
                    model="role-model",
                )

            self.assertEqual(result, "response")
            self.assertEqual(call.await_args.kwargs["provider"], "groq")
            self.assertEqual(call.await_args.kwargs["request_kind"], request_kind)
            self.assertEqual(call.await_args.kwargs["model"], "role-model")


if __name__ == "__main__":
    unittest.main()
