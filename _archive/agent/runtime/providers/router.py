from __future__ import annotations

from typing import Any

from .clients import _groq_chat, _ollama_chat, _openai_compatible_chat
from .errors import AgentProviderError
from .registry import provider_spec


async def provider_chat(
    *,
    provider: str,
    system_prompt: str,
    messages: list[dict[str, str]],
    temperature: float = 0.4,
    conversation_id: str | None = None,
    request_kind: str = "chat_reply",
    model: str | None = None,
    timeout_seconds: float | None = None,
    response_format: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | str | None = None,
) -> str:
    """Route a role-specific prompt through an existing provider client."""
    normalized = provider.strip().casefold()
    spec = provider_spec(normalized)
    common = {
        "temperature": temperature,
        "conversation_id": conversation_id,
        "request_kind": request_kind,
        "model": model,
    }
    if spec and spec.transport == "groq":
        return await _groq_chat(
            system_prompt,
            messages,
            timeout_seconds=timeout_seconds,
            tools=tools,
            tool_choice=tool_choice,
            **common,
        )
    if spec and spec.transport == "openai_compatible":
        return await _openai_compatible_chat(
            normalized,
            system_prompt,
            messages,
            timeout_seconds=timeout_seconds,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            **common,
        )
    if spec and spec.transport == "ollama":
        return await _ollama_chat(system_prompt, messages, **common)
    raise AgentProviderError(f"Unsupported provider for text generation: {normalized or 'empty'}")
