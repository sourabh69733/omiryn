from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from agent.evals.behavior.judge import _provider_call as judge_provider_call
from agent.evals.behavior.simulated_user import _provider_call as simulated_user_provider_call
from agent.runtime.providers.chat import generate_agent_reply
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
            ("deepinfra", "fireworks", "groq", "ollama", "mock"),
        )
        self.assertEqual(EVAL_PROVIDER_NAMES, ("deepinfra", "fireworks", "groq", "mock"))
        self.assertEqual(OPENAI_COMPATIBLE_PROVIDERS, {"deepinfra", "fireworks"})
        self.assertEqual(PROVIDER_NAMES, tuple(PROVIDER_REGISTRY))

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
