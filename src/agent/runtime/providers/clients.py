from __future__ import annotations

import logging
import os
from time import perf_counter
from typing import Any

import httpx

from agent.runtime.usage import CHAT_REPLY

from .config import _deepinfra_api_key
from .errors import AgentProviderError
from .messages import _compact_chat_reply, _provider_messages
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

    async with httpx.AsyncClient(timeout=config["timeout_seconds"]) as client:
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
                raw_usage["rate_limit"] = _provider_rate_limit_headers(error.response)
                try:
                    raw_usage["error"] = error.response.json()
                    detail = _provider_error_detail(raw_usage["error"])
                except ValueError:
                    raw_usage["error_text"] = error.response.text[:500]
                    detail = error.response.text[:240]
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
    if provider == "deepinfra":
        api_key = _deepinfra_api_key()
        if not api_key:
            raise AgentProviderError(
                "DEEPINFRA_API_KEY or DEEPINFRA_TOKEN is required when "
                "AGENT_PROVIDER=deepinfra."
            )
        base_url = os.getenv("DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai")
        return {
            "api_key": api_key,
            "chat_url": f"{base_url.rstrip('/')}/chat/completions",
            "model": model or os.getenv(
                "DEEPINFRA_MODEL",
                "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            ),
            "timeout_seconds": int(os.getenv("DEEPINFRA_TIMEOUT_SECONDS", "45")),
        }

    if provider == "fireworks":
        api_key = os.getenv("FIREWORKS_API_KEY")
        if not api_key:
            raise AgentProviderError(
                "FIREWORKS_API_KEY is required when AGENT_PROVIDER=fireworks."
            )
        base_url = os.getenv(
            "FIREWORKS_BASE_URL",
            "https://api.fireworks.ai/inference/v1",
        )
        return {
            "api_key": api_key,
            "chat_url": f"{base_url.rstrip('/')}/chat/completions",
            "model": model or os.getenv(
                "FIREWORKS_MODEL",
                "accounts/fireworks/models/gpt-oss-120b",
            ),
            "timeout_seconds": int(os.getenv("FIREWORKS_TIMEOUT_SECONDS", "45")),
        }

    raise AgentProviderError(f"Unsupported OpenAI-compatible provider: {provider}")


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

    async with httpx.AsyncClient(timeout=45) as client:
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
                raw_usage["rate_limit"] = _groq_rate_limit_headers(error.response)
                try:
                    raw_usage["error"] = error.response.json()
                except ValueError:
                    raw_usage["error_text"] = error.response.text[:500]
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
            detail = ""
            try:
                raw_usage["error"] = error.response.json()
                detail = str(raw_usage["error"].get("error") or "")
            except ValueError:
                raw_usage["error_text"] = error.response.text[:500]
                detail = error.response.text[:240]
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
