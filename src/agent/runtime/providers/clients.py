from __future__ import annotations

import logging
import os
from time import perf_counter
from typing import Any

import httpx

from agent.runtime.usage import CHAT_REPLY

from .errors import AgentProviderError
from .messages import _compact_chat_reply, _provider_messages
from .registry import (
    provider_api_key,
    provider_base_url,
    provider_model,
    provider_spec,
    provider_timeout_seconds,
)
from .usage_events import _elapsed_ms, _emit_prompt_debug, _prompt_debug, _record_usage_event, _sum_optional_ints

logger = logging.getLogger(__name__)


async def _openai_compatible_chat(
    provider: str,
    system_prompt: str,
    messages: list[dict[str, str]],
    temperature: float = 0.4,
    conversation_id: str | None = None,
    request_kind: str = "chat_reply",
    model: str | None = None,
    timeout_seconds: float | None = None,
) -> str:
    config = _openai_compatible_provider_config(provider, model)
    provider_messages = _provider_messages(messages)
    payload = {
        "model": config["model"],
        "messages": [{"role": "system", "content": system_prompt}] + provider_messages,
        "temperature": temperature,
    }
    prompt_debug = _prompt_debug(system_prompt, provider_messages)
    _emit_prompt_debug(provider, str(config["model"]), request_kind, prompt_debug)
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }

    request_timeout = (
        timeout_seconds if timeout_seconds is not None else float(config["timeout_seconds"])
    )
    async with httpx.AsyncClient(timeout=request_timeout) as client:
        logger.info(
            "agent.%s.request model=%s messages=%s temperature=%s",
            provider,
            config["model"],
            len(payload["messages"]),
            temperature,
        )
        started_at = perf_counter()
        try:
            response = await client.post(str(config["chat_url"]), json=payload, headers=headers)
            response.raise_for_status()
            latency_ms = _elapsed_ms(started_at)
            logger.info("agent.%s.response status_code=%s", provider, response.status_code)
            data = response.json()
            usage = data.get("usage") or {}
            raw_usage = {
                **usage,
                "rate_limit": _provider_rate_limit_headers(response),
                "prompt_debug": prompt_debug,
            }
            _record_usage_event(
                conversation_id=conversation_id,
                request_kind=request_kind,
                provider=provider,
                model=str(config["model"]),
                success=True,
                latency_ms=latency_ms,
                raw_usage=raw_usage,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
            )
            content = data["choices"][0]["message"]["content"]
            if request_kind == CHAT_REPLY:
                return _compact_chat_reply(content, messages)
            return content
        except httpx.HTTPStatusError as error:
            raw_usage = {"prompt_debug": prompt_debug}
            detail = ""
            if error.response is not None:
                raw_usage["error_status_code"] = error.response.status_code
                raw_usage["rate_limit"] = _provider_rate_limit_headers(error.response)
                try:
                    detail = _provider_error_detail(error.response.json())
                except ValueError:
                    detail = ""
            _record_usage_event(
                conversation_id=conversation_id,
                request_kind=request_kind,
                provider=provider,
                model=str(config["model"]),
                success=False,
                latency_ms=_elapsed_ms(started_at),
                raw_usage=raw_usage,
                error=str(error),
            )
            if detail:
                raise AgentProviderError(
                    f"{provider} returned HTTP {error.response.status_code}: {detail}"
                ) from error
            raise
        except Exception as error:
            _record_usage_event(
                conversation_id=conversation_id,
                request_kind=request_kind,
                provider=provider,
                model=str(config["model"]),
                success=False,
                latency_ms=_elapsed_ms(started_at),
                raw_usage={"prompt_debug": prompt_debug},
                error=str(error),
            )
            raise

def _openai_compatible_provider_config(
    provider: str,
    model: str | None,
) -> dict[str, str | int]:
    spec = provider_spec(provider)
    if spec is None or spec.transport != "openai_compatible":
        raise AgentProviderError(f"Unsupported OpenAI-compatible provider: {provider}")
    api_key = provider_api_key(provider)
    if not api_key:
        expected = " or ".join(spec.api_key_envs)
        raise AgentProviderError(f"{expected} is required when AGENT_PROVIDER={provider}.")
    base_url = provider_base_url(provider)
    assert base_url is not None
    return {
        "api_key": api_key,
        "chat_url": f"{base_url.rstrip('/')}/chat/completions",
        "model": model or provider_model(provider) or spec.default_model,
        "timeout_seconds": provider_timeout_seconds(provider),
    }


def _provider_error_detail(error_payload: Any) -> str:
    if isinstance(error_payload, dict):
        error = error_payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
            code = str(error.get("code") or "").strip()
            if message and code:
                return f"{message} ({code})"
            if message:
                return message
        message = str(error_payload.get("message") or "").strip()
        if message:
            return message
    return ""

def _provider_rate_limit_headers(response: httpx.Response) -> dict[str, str]:
    return {
        name: value
        for name, value in response.headers.items()
        if name.lower().startswith("x-ratelimit") or name.lower() == "retry-after"
    }

async def _groq_chat(
    system_prompt: str,
    messages: list[dict[str, str]],
    temperature: float = 0.4,
    conversation_id: str | None = None,
    request_kind: str = "chat_reply",
    model: str | None = None,
    timeout_seconds: float | None = None,
) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise AgentProviderError("GROQ_API_KEY is required when AGENT_PROVIDER=groq.")

    provider_messages = _provider_messages(messages)
    payload = {
        "model": model or os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        "messages": [{"role": "system", "content": system_prompt}] + provider_messages,
        "temperature": temperature,
    }
    prompt_debug = _prompt_debug(system_prompt, provider_messages)
    _emit_prompt_debug("groq", payload["model"], request_kind, prompt_debug)
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(timeout=timeout_seconds or 45) as client:
        logger.info(
            "agent.groq.request model=%s messages=%s temperature=%s",
            payload["model"],
            len(payload["messages"]),
            temperature,
        )
        started_at = perf_counter()
        try:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            latency_ms = _elapsed_ms(started_at)
            logger.info("agent.groq.response status_code=%s", response.status_code)
            data = response.json()
            usage = data.get("usage") or {}
            raw_usage = {
                **usage,
                "rate_limit": _groq_rate_limit_headers(response),
                "prompt_debug": prompt_debug,
            }
            _record_usage_event(
                conversation_id=conversation_id,
                request_kind=request_kind,
                provider="groq",
                model=payload["model"],
                success=True,
                latency_ms=latency_ms,
                raw_usage=raw_usage,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
            )
            content = data["choices"][0]["message"]["content"]
            if request_kind == "chat_reply":
                return _compact_chat_reply(content, messages)
            return content
        except httpx.HTTPStatusError as error:
            raw_usage = {"prompt_debug": prompt_debug}
            if error.response is not None:
                raw_usage["error_status_code"] = error.response.status_code
                raw_usage["rate_limit"] = _groq_rate_limit_headers(error.response)
            _record_usage_event(
                conversation_id=conversation_id,
                request_kind=request_kind,
                provider="groq",
                model=payload["model"],
                success=False,
                latency_ms=_elapsed_ms(started_at),
                raw_usage=raw_usage,
                error=str(error),
            )
            raise
        except Exception as error:
            _record_usage_event(
                conversation_id=conversation_id,
                request_kind=request_kind,
                provider="groq",
                model=payload["model"],
                success=False,
                latency_ms=_elapsed_ms(started_at),
                raw_usage={"prompt_debug": prompt_debug},
                error=str(error),
            )
            raise

def _groq_rate_limit_headers(response: httpx.Response) -> dict[str, str]:
    header_names = [
        "retry-after",
        "x-ratelimit-limit-requests",
        "x-ratelimit-limit-tokens",
        "x-ratelimit-remaining-requests",
        "x-ratelimit-remaining-tokens",
        "x-ratelimit-reset-requests",
        "x-ratelimit-reset-tokens",
    ]
    return {
        name: response.headers[name]
        for name in header_names
        if name in response.headers
    }

async def _ollama_chat(
    system_prompt: str,
    messages: list[dict[str, str]],
    temperature: float = 0.4,
    conversation_id: str | None = None,
    request_kind: str = "chat_reply",
    model: str | None = None,
) -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    provider_messages = _provider_messages(messages)
    payload = {
        "model": model or os.getenv("OLLAMA_MODEL", "llama3.1"),
        "messages": [{"role": "system", "content": system_prompt}] + provider_messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    prompt_debug = _prompt_debug(system_prompt, provider_messages)
    _emit_prompt_debug("ollama", payload["model"], request_kind, prompt_debug)

    async with httpx.AsyncClient(timeout=90) as client:
        started_at = perf_counter()
        try:
            response = await client.post(f"{base_url}/api/chat", json=payload)
            response.raise_for_status()
            latency_ms = _elapsed_ms(started_at)
            data = response.json()
            prompt_tokens = data.get("prompt_eval_count")
            completion_tokens = data.get("eval_count")
            _record_usage_event(
                conversation_id=conversation_id,
                request_kind=request_kind,
                provider="ollama",
                model=payload["model"],
                success=True,
                latency_ms=latency_ms,
                raw_usage={**data, "prompt_debug": prompt_debug},
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=_sum_optional_ints(prompt_tokens, completion_tokens),
            )
            content = data["message"]["content"]
            if request_kind == "chat_reply":
                return _compact_chat_reply(content, messages)
            return content
        except httpx.HTTPStatusError as error:
            raw_usage = {"prompt_debug": prompt_debug}
            raw_usage["error_status_code"] = error.response.status_code
            detail = ""
            try:
                error_payload = error.response.json()
                detail = str(error_payload.get("error") or "") if isinstance(error_payload, dict) else ""
            except ValueError:
                detail = ""
            _record_usage_event(
                conversation_id=conversation_id,
                request_kind=request_kind,
                provider="ollama",
                model=payload["model"],
                success=False,
                latency_ms=_elapsed_ms(started_at),
                raw_usage=raw_usage,
                error=str(error),
            )
            if error.response.status_code == 404:
                raise AgentProviderError(
                    "Ollama returned 404 for "
                    f"{base_url}/api/chat using model '{payload['model']}'. "
                    f"{detail or 'Check that the model is installed.'} "
                    "Run `ollama list` and set OLLAMA_MODEL to an installed tag, "
                    "for example `llama3.1:8b`."
                ) from error
            raise
        except Exception as error:
            _record_usage_event(
                conversation_id=conversation_id,
                request_kind=request_kind,
                provider="ollama",
                model=payload["model"],
                success=False,
                latency_ms=_elapsed_ms(started_at),
                raw_usage={"prompt_debug": prompt_debug},
                error=str(error),
            )
            raise
