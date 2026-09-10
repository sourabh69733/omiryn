"""Calls provider embedding endpoints through one provider-neutral contract."""

from __future__ import annotations

import math
from time import perf_counter

import httpx

from agent.providers.shared.errors import AgentProviderError
from agent.providers.shared.usage_events import _elapsed_ms, _record_usage_event

from .registry import (
    provider_api_key,
    provider_base_url,
    provider_spec,
    provider_timeout_seconds,
)


async def provider_embeddings(
    *,
    provider: str,
    model: str,
    inputs: list[str],
    conversation_id: str | None = None,
    request_kind: str = "memory_embedding",
) -> list[list[float]]:
    """Embed a non-empty text batch using an OpenAI-compatible provider."""
    normalized_provider = provider.strip().casefold()
    normalized_model = model.strip()
    clean_inputs = [str(value).strip() for value in inputs]
    if not normalized_model or not clean_inputs or any(not value for value in clean_inputs):
        raise ValueError("embedding request requires a model and non-empty inputs")
    spec = provider_spec(normalized_provider)
    if spec is None or spec.transport != "openai_compatible":
        raise AgentProviderError(
            f"Provider does not support the embedding gateway: {normalized_provider or 'empty'}"
        )
    api_key = provider_api_key(normalized_provider)
    if not api_key:
        raise AgentProviderError(f"{' or '.join(spec.api_key_envs)} is required for embeddings")
    base_url = provider_base_url(normalized_provider)
    assert base_url is not None
    payload = {"model": normalized_model, "input": clean_inputs}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    started_at = perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=float(provider_timeout_seconds(normalized_provider))
        ) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/embeddings",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
        data = response.json()
        vectors = _embedding_vectors(data, expected_count=len(clean_inputs))
        usage = data.get("usage") or {}
        _record_usage_event(
            conversation_id=conversation_id,
            request_kind=request_kind,
            provider=normalized_provider,
            model=normalized_model,
            success=True,
            latency_ms=_elapsed_ms(started_at),
            raw_usage=usage,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=0,
            total_tokens=usage.get("total_tokens"),
        )
        return vectors
    except Exception as error:
        _record_usage_event(
            conversation_id=conversation_id,
            request_kind=request_kind,
            provider=normalized_provider,
            model=normalized_model,
            success=False,
            latency_ms=_elapsed_ms(started_at),
            raw_usage={},
            error=str(error),
        )
        raise


def _embedding_vectors(payload: object, *, expected_count: int) -> list[list[float]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise AgentProviderError("Embedding provider returned an invalid response")
    ordered = sorted(payload["data"], key=lambda item: int(item.get("index", -1)))
    if len(ordered) != expected_count:
        raise AgentProviderError("Embedding provider returned the wrong vector count")
    vectors: list[list[float]] = []
    dimensions: int | None = None
    for item in ordered:
        values = item.get("embedding") if isinstance(item, dict) else None
        if not isinstance(values, list) or not values:
            raise AgentProviderError("Embedding provider returned an empty vector")
        vector = [float(value) for value in values]
        if any(not math.isfinite(value) for value in vector):
            raise AgentProviderError("Embedding provider returned a non-finite vector")
        dimensions = dimensions or len(vector)
        if len(vector) != dimensions:
            raise AgentProviderError("Embedding provider returned mixed vector dimensions")
        vectors.append(vector)
    return vectors


__all__ = ["provider_embeddings"]
