"""Runs companion reply generation through the selected model gateway."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from agent.observability.usage import CHAT_REPLY, INPUT_GUARDRAIL
from agent.providers.gateway.claude import claude_key, is_claude
from agent.providers.gateway.claude_chat import claude_chat
from agent.providers.gateway.registry import provider_model
from agent.providers.shared.errors import AgentProviderError, AgentProviderTruncationError

from agent.providers.shared.config import ONBOARDING_SYSTEM_PROMPT, _provider_name
from agent.providers.shared.messages import _user_message_count
from agent.providers.shared.mock import _mock_reply
from .prompts import _system_prompt_with_context
from .quality import assess_user_message_quality
from agent.providers.gateway.router import provider_chat
from agent.providers.shared.usage_events import _record_usage_event

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
    response_format: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | str | None = None,
    max_tokens: int | None = None,
    timeout_seconds: float | None = None,
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
    if is_claude(model) and not claude_key():
        # A Claude reply model with no key set: the usual model replies, as if none was named.
        logger.warning("agent.reply.claude_without_key model=%s", model)
        model = None

    async def call(chosen_model: str | None) -> str:
        prompt = system_prompt or _system_prompt_with_context(
            ONBOARDING_SYSTEM_PROMPT,
            context_sources,
            agent_mode,
            agent_tone,
            user_profile,
            agent_name,
        )
        output_tokens = max_tokens or int(os.getenv("AGENT_CHAT_MAX_OUTPUT_TOKENS", "1200"))
        wait_seconds = timeout_seconds if timeout_seconds is not None else reply_timeout_seconds()
        if is_claude(chosen_model):
            # Claude has its own path: same prompt, history and tools, sent in Claude's format.
            return await claude_chat(
                prompt,
                messages,
                model=str(chosen_model),
                conversation_id=conversation_id,
                request_kind=CHAT_REPLY,
                tools=tools,
                tool_choice=tool_choice,
                max_tokens=output_tokens,
                timeout_seconds=wait_seconds,
            )
        return await provider_chat(
            provider=provider,
            system_prompt=prompt,
            messages=messages,
            conversation_id=conversation_id,
            request_kind=CHAT_REPLY,
            model=chosen_model,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            max_tokens=output_tokens,
            timeout_seconds=wait_seconds,
        )

    try:
        return await call(model)
    except AgentProviderTruncationError:
        raise
    except (httpx.TimeoutException, httpx.TransportError, AgentProviderError) as error:
        # A stalled or failing model gets one try on another model before the user sees a failure.
        fallback = reply_fallback_model(provider, model)
        if fallback is None:
            raise
        logger.warning(
            "agent.reply.fallback provider=%s from=%s to=%s error=%s",
            provider,
            model or provider_model(provider),
            fallback,
            type(error).__name__,
        )
        return await call(fallback)


def reply_timeout_seconds() -> float:
    """How long a user waits on one model call before the fallback (AGENT_REPLY_TIMEOUT_SECONDS)."""
    try:
        return max(5.0, float(os.getenv("AGENT_REPLY_TIMEOUT_SECONDS", "25")))
    except ValueError:
        return 25.0


# Known-fast backups; the next "available" model can be a slow one (gpt-oss-120b takes ~90s).
_DEFAULT_FALLBACK_MODELS = {"deepinfra": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"}


def reply_fallback_model(provider: str, model: str | None) -> str | None:
    """AGENT_REPLY_FALLBACK_MODEL, else a known-fast model for the provider; 'off' disables."""
    primary = model or provider_model(provider)
    configured = os.getenv("AGENT_REPLY_FALLBACK_MODEL", "").strip()
    if configured.lower() in {"off", "none", "false"}:
        return None
    # When Claude was the reply model, the provider's own model is the natural backup.
    fallback = configured or (provider_model(provider) if is_claude(primary) else _DEFAULT_FALLBACK_MODELS.get(provider))
    return fallback if fallback and fallback != primary else None
