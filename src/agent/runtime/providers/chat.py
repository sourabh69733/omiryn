from __future__ import annotations

import logging
from typing import Any

from agent.runtime.usage import CHAT_REPLY, INPUT_GUARDRAIL

from .clients import _groq_chat, _ollama_chat, _openai_compatible_chat
from .config import ONBOARDING_SYSTEM_PROMPT, OPENAI_COMPATIBLE_PROVIDERS, _provider_name
from .errors import AgentProviderError
from .messages import _user_message_count
from .mock import _mock_reply
from .prompts import _system_prompt_with_context
from .quality import assess_user_message_quality
from .usage_events import _record_usage_event

logger = logging.getLogger(__name__)


async def generate_agent_reply(
    messages: list[dict[str, str]],
    conversation_id: str | None = None,
    model: str | None = None,
    agent_mode: str = "know_me",
    agent_tone: str = "auto",
    agent_name: str | None = None,
    context_sources: list[dict[str, Any]] | None = None,
    user_profile: dict[str, Any] | None = None,
    system_prompt: str | None = None,
) -> str:
    provider = _provider_name()
    logger.info("agent.reply provider=%s user_messages=%s", provider, _user_message_count(messages))
    quality = assess_user_message_quality(messages)
    if not quality["valid"]:
        _record_usage_event(
            conversation_id=conversation_id,
            request_kind=INPUT_GUARDRAIL,
            provider="guardrail",
            model="local",
            success=True,
            latency_ms=0,
        )
        return str(quality["reply"])

    if provider == "mock":
        _record_usage_event(
            conversation_id=conversation_id,
            request_kind=CHAT_REPLY,
            provider=provider,
            model=model or "mock",
            success=True,
            latency_ms=0,
        )
        return _mock_reply(messages, user_profile, agent_name)
    if provider == "groq":
        return await _groq_chat(
            system_prompt or _system_prompt_with_context(
                ONBOARDING_SYSTEM_PROMPT,
                context_sources,
                agent_mode,
                agent_tone,
                user_profile,
                agent_name,
            ),
            messages,
            conversation_id=conversation_id,
            request_kind=CHAT_REPLY,
            model=model,
        )
    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        return await _openai_compatible_chat(
            provider,
            system_prompt or _system_prompt_with_context(
                ONBOARDING_SYSTEM_PROMPT,
                context_sources,
                agent_mode,
                agent_tone,
                user_profile,
                agent_name,
            ),
            messages,
            conversation_id=conversation_id,
            request_kind=CHAT_REPLY,
            model=model,
        )
    if provider == "ollama":
        return await _ollama_chat(
            system_prompt or _system_prompt_with_context(
                ONBOARDING_SYSTEM_PROMPT,
                context_sources,
                agent_mode,
                agent_tone,
                user_profile,
                agent_name,
            ),
            messages,
            conversation_id=conversation_id,
            request_kind=CHAT_REPLY,
            model=model,
        )
    raise AgentProviderError(f"Unsupported AGENT_PROVIDER: {provider}")
