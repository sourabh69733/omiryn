from __future__ import annotations

import os
from typing import Any

from agent.context_engine.prompt_engine.versions.v1 import COMPANION_SYSTEM_PROMPT

from .registry import (
    OPENAI_COMPATIBLE_PROVIDERS as OPENAI_COMPATIBLE_PROVIDERS,
    available_models as _available_models,
    provider_api_key as _provider_api_key,
    provider_api_key_loaded as _provider_api_key_loaded,
    provider_model as _provider_model,
)

RECENT_CHAT_MESSAGE_LIMIT = int(os.getenv("AGENT_RECENT_MESSAGE_LIMIT", "8"))
CONTEXT_SOURCE_LIMIT = int(os.getenv("AGENT_CONTEXT_SOURCE_LIMIT", "5"))
CONTEXT_SOURCE_CHAR_LIMIT = int(os.getenv("AGENT_CONTEXT_SOURCE_CHAR_LIMIT", "2000"))
STYLE_CONTEXT_CHAR_LIMIT = int(os.getenv("AGENT_STYLE_CONTEXT_CHAR_LIMIT", "1500"))
CHAT_REPLY_WORD_LIMIT = int(os.getenv("AGENT_CHAT_REPLY_WORD_LIMIT", "35"))
CHAT_ADVICE_REPLY_WORD_LIMIT = int(os.getenv("AGENT_CHAT_ADVICE_REPLY_WORD_LIMIT", "80"))
STYLE_CONTEXT_TYPES = {"whatsapp_chat", "friend_style"}
ONBOARDING_SYSTEM_PROMPT = COMPANION_SYSTEM_PROMPT


def _provider_name() -> str:
    return os.getenv("AGENT_PROVIDER", "mock").strip().lower()

def agent_runtime_status() -> dict[str, Any]:
    provider = _provider_name()
    return {
        "provider": provider,
        "model": _provider_model(provider),
        "available_models": _available_models(provider),
        "api_key_loaded": _provider_api_key_loaded(provider),
        "groq_api_key_loaded": bool(os.getenv("GROQ_API_KEY")),
        "deepinfra_api_key_loaded": bool(_deepinfra_api_key()),
        "fireworks_api_key_loaded": bool(os.getenv("FIREWORKS_API_KEY")),
        "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    }

def _models_from_env(env_name: str, defaults: list[str]) -> list[str]:
    configured = [
        model.strip()
        for model in os.getenv(env_name, "").split(",")
        if model.strip()
    ]
    models = configured or defaults
    return list(dict.fromkeys(models))

def _deepinfra_api_key() -> str:
    return _provider_api_key("deepinfra")
