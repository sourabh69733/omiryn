"""Claude, through Anthropic's own SDK, for the few calls where a stronger writer is worth its price.

Everything else in the app talks to OpenAI-compatible providers through the gateway. This is a
separate, small path: one request that returns JSON matching a schema. A caller picks it by naming
a Claude model (CHAT_READ_MODEL=claude-sonnet-5-5); without a key or on any failure the caller
falls back to its usual model, so nothing depends on Claude being reachable. A chat reply written
by Claude is in claude_chat.py.

The key is read by the SDK from ANTHROPIC_API_KEY (CLAUDE_API_KEY is accepted as a second name).
"""

from __future__ import annotations

import json
import logging
import os
from time import perf_counter
from typing import Any

logger = logging.getLogger(__name__)

PROVIDER = "anthropic"
# US dollars per million tokens (input, output), list prices as of 2026-11-03. For the cost shown
# in the usage table and the compare script; the bill is the truth.
PRICES_PER_1M: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
# Models whose declined requests Anthropic can re-run on another model inside the same call.
_SERVER_FALLBACK = frozenset({"claude-sonnet-5-5", "claude-opus-5-5"})
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16000
DEFAULT_EFFORT = "medium"


class ClaudeUnavailable(RuntimeError):
    """No key, a refusal, or an answer that is not the JSON asked for: the caller uses its usual model."""


def is_claude(model: str | None) -> bool:
    return bool(model) and str(model).startswith("claude-")


def claude_key() -> str | None:
    return os.getenv("ANTHROPIC_API_KEY", "").strip() or os.getenv("CLAUDE_API_KEY", "").strip() or None


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    prices = PRICES_PER_1M.get(model)
    return round(input_tokens / 1_000_000 * prices[0] + output_tokens / 1_000_000 * prices[1], 6) if prices else None


async def claude_json(
    system_prompt: str,
    text: str,
    *,
    model: str,
    schema: dict[str, Any],
    request_kind: str,
    conversation_id: str | None = None,
    effort: str = DEFAULT_EFFORT,
    timeout_seconds: float | None = 120,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One request, one JSON object matching `schema`. Returns (the object, usage) where usage is
    {"model", "input_tokens", "output_tokens", "cost_usd", "seconds"}. Raises ClaudeUnavailable
    when there is no key, the request is declined, or the answer cannot be read."""
    import anthropic

    key = claude_key()
    if not key:
        raise ClaudeUnavailable("no Claude key is set")
    client = anthropic.AsyncAnthropic(api_key=key, timeout=timeout_seconds or 600.0)
    request: dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": system_prompt,
        "messages": [{"role": "user", "content": text}],
        # Thinking is left to the model (adaptive is the default on these models); effort sets how
        # much. No temperature: the current models reject sampling settings.
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    }
    started = perf_counter()
    try:
        if model in _SERVER_FALLBACK:
            # A declined request is re-run by Anthropic on the model it recommends, in the same call.
            response = await client.beta.messages.create(**request, betas=[_FALLBACK_BETA], fallbacks="default")
        else:
            response = await client.messages.create(**request)
    except anthropic.APIStatusError as error:
        _record(request_kind, conversation_id, model, started, success=False)
        raise ClaudeUnavailable(f"Claude returned {error.status_code}") from error
    except anthropic.APIConnectionError as error:
        _record(request_kind, conversation_id, model, started, success=False)
        raise ClaudeUnavailable("could not reach Claude") from error
    finally:
        await client.close()
    usage = {
        "model": response.model,
        "input_tokens": int(response.usage.input_tokens or 0),
        "output_tokens": int(response.usage.output_tokens or 0),
        "seconds": round(perf_counter() - started, 1),
    }
    usage["cost_usd"] = cost_usd(model, usage["input_tokens"], usage["output_tokens"])
    _record(request_kind, conversation_id, model, started, success=response.stop_reason != "refusal", usage=usage)
    if response.stop_reason == "refusal":
        raise ClaudeUnavailable("Claude declined this request")
    written = next((block.text for block in response.content if block.type == "text"), "")
    try:
        data = json.loads(written)
    except json.JSONDecodeError as error:
        raise ClaudeUnavailable(f"Claude stopped early ({response.stop_reason})") from error
    if not isinstance(data, dict):
        raise ClaudeUnavailable("Claude did not return an object")
    return data, usage


def _record(request_kind: str, conversation_id: str | None, model: str, started: float, *, success: bool, usage: dict[str, Any] | None = None, raw_usage: dict[str, Any] | None = None) -> None:
    """The same usage row every other model call writes, so spend shows up in one place."""
    from storage import save_agent_usage_event

    usage = usage or {}
    logger.info(
        "agent.usage provider=%s model=%s kind=%s success=%s prompt_tokens=%s completion_tokens=%s estimated_cost_usd=%s",
        PROVIDER, model, request_kind, success, usage.get("input_tokens"), usage.get("output_tokens"), usage.get("cost_usd"),
    )
    if not conversation_id:
        return  # a usage row belongs to a user; a call with no chat behind it is only logged
    try:
        save_agent_usage_event({
            "conversation_id": conversation_id,
            "request_kind": request_kind,
            "provider": PROVIDER,
            "model": model,
            "success": success,
            "prompt_tokens": usage.get("input_tokens"),
            "completion_tokens": usage.get("output_tokens"),
            "total_tokens": (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0) if usage else None,
            "latency_ms": int((perf_counter() - started) * 1000),
            "estimated_cost_usd": usage.get("cost_usd"),
            "error": None if success else "provider_error",
            "raw_usage": raw_usage or {},
        })
    except Exception as error:
        logger.error("agent.usage.persist_failed error_type=%s", type(error).__name__)


__all__ = ["ClaudeUnavailable", "PRICES_PER_1M", "claude_json", "claude_key", "cost_usd", "is_claude"]
