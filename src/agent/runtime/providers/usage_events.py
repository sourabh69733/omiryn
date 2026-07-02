from __future__ import annotations

import logging
import os
from time import perf_counter
from typing import Any

from storage import save_agent_usage_event

logger = logging.getLogger(__name__)


def _record_usage_event(
    *,
    conversation_id: str | None,
    request_kind: str,
    provider: str,
    model: str | None,
    success: bool,
    latency_ms: int | None,
    raw_usage: dict[str, Any] | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    error: str | None = None,
) -> None:
    event = {
        "conversation_id": conversation_id,
        "request_kind": request_kind,
        "provider": provider,
        "model": model,
        "success": success,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "latency_ms": latency_ms,
        "estimated_cost_usd": _estimated_cost_usd(provider, prompt_tokens, completion_tokens),
        "error": error[:500] if error else None,
        "raw_usage": raw_usage or {},
    }
    logger.info(
        "agent.usage provider=%s model=%s kind=%s success=%s prompt_tokens=%s "
        "completion_tokens=%s total_tokens=%s latency_ms=%s estimated_cost_usd=%s",
        provider,
        model,
        request_kind,
        success,
        prompt_tokens,
        completion_tokens,
        total_tokens,
        latency_ms,
        event["estimated_cost_usd"],
    )
    try:
        save_agent_usage_event(event)
    except Exception:
        logger.exception("agent.usage.persist_failed")

def _prompt_debug(
    system_prompt: str,
    provider_messages: list[dict[str, str]],
) -> dict[str, Any]:
    message_chars = sum(len(str(message.get("content") or "")) for message in provider_messages)
    total_chars = len(system_prompt) + message_chars
    return {
        "system_chars": len(system_prompt),
        "message_chars": message_chars,
        "total_chars": total_chars,
        "rough_tokens": round(total_chars / 4),
        "provider_message_count": len(provider_messages),
    }

def _emit_prompt_debug(
    provider: str,
    model: str | None,
    request_kind: str,
    prompt_debug: dict[str, Any],
) -> None:
    message = (
        "agent.prompt_size "
        f"provider={provider} model={model or 'unknown'} kind={request_kind} "
        f"chars={prompt_debug['total_chars']} rough_tokens={prompt_debug['rough_tokens']} "
        f"system_chars={prompt_debug['system_chars']} "
        f"message_chars={prompt_debug['message_chars']} "
        f"messages={prompt_debug['provider_message_count']}"
    )
    logger.info(message)
    if os.getenv("AGENT_PROMPT_DEBUG", "true").lower() == "true":
        print(message, flush=True)

def _estimated_cost_usd(
    provider: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float | None:
    if prompt_tokens is None or completion_tokens is None:
        return None

    input_cost_per_1m, output_cost_per_1m = _provider_token_costs(provider)
    if input_cost_per_1m == 0 and output_cost_per_1m == 0:
        return None

    return round(
        (prompt_tokens / 1_000_000 * input_cost_per_1m)
        + (completion_tokens / 1_000_000 * output_cost_per_1m),
        8,
    )

def _provider_token_costs(provider: str) -> tuple[float, float]:
    env_prefixes = {
        "groq": "GROQ",
        "deepinfra": "DEEPINFRA",
        "fireworks": "FIREWORKS",
    }
    env_prefix = env_prefixes.get(provider)
    if not env_prefix:
        return 0.0, 0.0
    input_cost = float(os.getenv(f"{env_prefix}_INPUT_COST_PER_1M", "0") or 0)
    output_cost = float(os.getenv(f"{env_prefix}_OUTPUT_COST_PER_1M", "0") or 0)
    return input_cost, output_cost

def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)

def _sum_optional_ints(first: int | None, second: int | None) -> int | None:
    if first is None and second is None:
        return None
    return (first or 0) + (second or 0)
