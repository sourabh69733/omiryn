from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

ProviderTransport = Literal["openai_compatible", "groq", "ollama", "mock"]


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    transport: ProviderTransport
    model_env: str
    default_model: str
    available_models_env: str
    default_available_models: tuple[str, ...]
    api_key_envs: tuple[str, ...] = ()
    base_url_env: str | None = None
    default_base_url: str | None = None
    timeout_env: str | None = None
    default_timeout_seconds: int = 45
    evaluation_enabled: bool = True


PROVIDER_REGISTRY = {
    "deepinfra": ProviderSpec(
        name="deepinfra",
        transport="openai_compatible",
        api_key_envs=("DEEPINFRA_API_KEY", "DEEPINFRA_TOKEN"),
        base_url_env="DEEPINFRA_BASE_URL",
        default_base_url="https://api.deepinfra.com/v1/openai",
        model_env="DEEPINFRA_MODEL",
        default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        available_models_env="DEEPINFRA_AVAILABLE_MODELS",
        default_available_models=(
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "meta-llama/Llama-3.1-70B-Instruct-Turbo",
            "deepseek-ai/DeepSeek-V3",
        ),
        timeout_env="DEEPINFRA_TIMEOUT_SECONDS",
    ),
    "fireworks": ProviderSpec(
        name="fireworks",
        transport="openai_compatible",
        api_key_envs=("FIREWORKS_API_KEY",),
        base_url_env="FIREWORKS_BASE_URL",
        default_base_url="https://api.fireworks.ai/inference/v1",
        model_env="FIREWORKS_MODEL",
        default_model="accounts/fireworks/models/gpt-oss-120b",
        available_models_env="FIREWORKS_AVAILABLE_MODELS",
        default_available_models=(
            "accounts/fireworks/models/gpt-oss-120b",
            "accounts/fireworks/models/llama-v3p3-70b-instruct",
            "accounts/fireworks/models/deepseek-v3p1",
        ),
        timeout_env="FIREWORKS_TIMEOUT_SECONDS",
    ),
    "groq": ProviderSpec(
        name="groq",
        transport="groq",
        api_key_envs=("GROQ_API_KEY",),
        model_env="GROQ_MODEL",
        default_model="llama-3.1-8b-instant",
        available_models_env="GROQ_AVAILABLE_MODELS",
        default_available_models=("llama-3.3-70b-versatile", "llama-3.1-8b-instant"),
    ),
    "ollama": ProviderSpec(
        name="ollama",
        transport="ollama",
        base_url_env="OLLAMA_BASE_URL",
        default_base_url="http://localhost:11434",
        model_env="OLLAMA_MODEL",
        default_model="llama3.1:8b",
        available_models_env="OLLAMA_AVAILABLE_MODELS",
        default_available_models=("llama3.1:8b",),
        default_timeout_seconds=90,
        evaluation_enabled=False,
    ),
    "mock": ProviderSpec(
        name="mock",
        transport="mock",
        model_env="MOCK_MODEL",
        default_model="mock",
        available_models_env="MOCK_AVAILABLE_MODELS",
        default_available_models=("mock",),
    ),
}

PROVIDER_NAMES = tuple(PROVIDER_REGISTRY)
EVAL_PROVIDER_NAMES = tuple(
    name for name, spec in PROVIDER_REGISTRY.items() if spec.evaluation_enabled
)
OPENAI_COMPATIBLE_PROVIDERS = {
    name for name, spec in PROVIDER_REGISTRY.items() if spec.transport == "openai_compatible"
}


def provider_spec(provider: str) -> ProviderSpec | None:
    return PROVIDER_REGISTRY.get(provider.strip().casefold())


def provider_model(provider: str) -> str | None:
    spec = provider_spec(provider)
    return os.getenv(spec.model_env, spec.default_model) if spec else None


def available_models(provider: str) -> list[str]:
    spec = provider_spec(provider)
    if spec is None:
        return []
    configured = [
        model.strip()
        for model in os.getenv(spec.available_models_env, "").split(",")
        if model.strip()
    ]
    if configured:
        return list(dict.fromkeys(configured))
    return list(dict.fromkeys((provider_model(provider), *spec.default_available_models)))


def provider_api_key(provider: str) -> str:
    spec = provider_spec(provider)
    if spec is None:
        return ""
    return next((os.getenv(name, "") for name in spec.api_key_envs if os.getenv(name)), "")


def provider_api_key_loaded(provider: str) -> bool:
    spec = provider_spec(provider)
    return bool(spec and (not spec.api_key_envs or provider_api_key(provider)))


def provider_base_url(provider: str) -> str | None:
    spec = provider_spec(provider)
    if spec is None or spec.default_base_url is None:
        return None
    return (
        os.getenv(spec.base_url_env, spec.default_base_url)
        if spec.base_url_env
        else spec.default_base_url
    )


def provider_timeout_seconds(provider: str) -> int:
    spec = provider_spec(provider)
    if spec is None:
        return 45
    value = (
        os.getenv(spec.timeout_env, str(spec.default_timeout_seconds))
        if spec.timeout_env
        else spec.default_timeout_seconds
    )
    return int(value)


def provider_env_prefix(provider: str) -> str | None:
    spec = provider_spec(provider)
    return spec.name.upper().replace("-", "_") if spec else None
