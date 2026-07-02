from __future__ import annotations

import os
from typing import Any

from agent.context_engine.prompt_engine.versions.v1 import COMPANION_SYSTEM_PROMPT

RECENT_CHAT_MESSAGE_LIMIT = int(os.getenv("AGENT_RECENT_MESSAGE_LIMIT", "12"))
CONTEXT_SOURCE_LIMIT = int(os.getenv("AGENT_CONTEXT_SOURCE_LIMIT", "5"))
CONTEXT_SOURCE_CHAR_LIMIT = int(os.getenv("AGENT_CONTEXT_SOURCE_CHAR_LIMIT", "2000"))
STYLE_CONTEXT_CHAR_LIMIT = int(os.getenv("AGENT_STYLE_CONTEXT_CHAR_LIMIT", "1500"))
CHAT_REPLY_WORD_LIMIT = int(os.getenv("AGENT_CHAT_REPLY_WORD_LIMIT", "35"))
CHAT_ADVICE_REPLY_WORD_LIMIT = int(os.getenv("AGENT_CHAT_ADVICE_REPLY_WORD_LIMIT", "80"))
STYLE_CONTEXT_TYPES = {"whatsapp_chat", "friend_style"}
OPENAI_COMPATIBLE_PROVIDERS = {"deepinfra", "fireworks"}
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

def _provider_model(provider: str) -> str | None:
    if provider == "groq":
        return os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    if provider == "deepinfra":
        return os.getenv("DEEPINFRA_MODEL", "meta-llama/Llama-3.3-70B-Instruct-Turbo")
    if provider == "fireworks":
        return os.getenv("FIREWORKS_MODEL", "accounts/fireworks/models/gpt-oss-120b")
    if provider == "ollama":
        return os.getenv("OLLAMA_MODEL", "llama3.1")
    if provider == "mock":
        return "mock"
    return None

def _available_models(provider: str) -> list[str]:
    if provider == "groq":
        return _models_from_env(
            "GROQ_AVAILABLE_MODELS",
            [
                os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
                "llama-3.3-70b-versatile",
                "llama-3.1-8b-instant",
            ],
        )
    if provider == "deepinfra":
        return _models_from_env(
            "DEEPINFRA_AVAILABLE_MODELS",
            [
                os.getenv("DEEPINFRA_MODEL", "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
                "meta-llama/Llama-3.1-70B-Instruct-Turbo",
                "deepseek-ai/DeepSeek-V3",
            ],
        )
    if provider == "fireworks":
        return _models_from_env(
            "FIREWORKS_AVAILABLE_MODELS",
            [
                os.getenv("FIREWORKS_MODEL", "accounts/fireworks/models/gpt-oss-120b"),
                "accounts/fireworks/models/llama-v3p3-70b-instruct",
                "accounts/fireworks/models/deepseek-v3p1",
            ],
        )
    if provider == "ollama":
        return _models_from_env("OLLAMA_AVAILABLE_MODELS", [os.getenv("OLLAMA_MODEL", "llama3.1")])
    if provider == "mock":
        return ["mock"]
    return []

def _provider_api_key_loaded(provider: str) -> bool:
    if provider == "groq":
        return bool(os.getenv("GROQ_API_KEY"))
    if provider == "deepinfra":
        return bool(_deepinfra_api_key())
    if provider == "fireworks":
        return bool(os.getenv("FIREWORKS_API_KEY"))
    if provider in {"mock", "ollama"}:
        return True
    return False

def _models_from_env(env_name: str, defaults: list[str]) -> list[str]:
    configured = [
        model.strip()
        for model in os.getenv(env_name, "").split(",")
        if model.strip()
    ]
    models = configured or defaults
    return list(dict.fromkeys(models))

def _deepinfra_api_key() -> str:
    return os.getenv("DEEPINFRA_API_KEY") or os.getenv("DEEPINFRA_TOKEN") or ""
