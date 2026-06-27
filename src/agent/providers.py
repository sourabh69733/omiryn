from __future__ import annotations

import json
import logging
import os
import re
from time import perf_counter
from typing import Any

import httpx

from agent.extraction import normalize_extracted_profile
from agent.behavior import (
    agent_persona_for_interest,
    behavior_prompt,
    tone_prompt,
)
from agent.prompt_builder import (
    build_companion_system_prompt,
    context_sources_text,
    truncate_for_context,
)
from agent.prompt_sections import (
    COMPANION_SYSTEM_PROMPT,
    DATA_POINT_EXTRACTION_SYSTEM_PROMPT,
    DATA_POINT_REVIEW_SYSTEM_PROMPT,
    DEEP_FACT_EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_REPAIR_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
)
from agent.usage import (
    CHAT_REPLY,
    DATA_POINT_EXTRACT,
    INPUT_GUARDRAIL,
    PROFILE_EXTRACT,
    PROFILE_EXTRACT_REPAIR,
    PROFILE_FACT_EXTRACT,
)
from storage import save_agent_usage_event

logger = logging.getLogger(__name__)

RECENT_CHAT_MESSAGE_LIMIT = int(os.getenv("AGENT_RECENT_MESSAGE_LIMIT", "12"))
CONTEXT_SOURCE_LIMIT = int(os.getenv("AGENT_CONTEXT_SOURCE_LIMIT", "5"))
CONTEXT_SOURCE_CHAR_LIMIT = int(os.getenv("AGENT_CONTEXT_SOURCE_CHAR_LIMIT", "2000"))
STYLE_CONTEXT_CHAR_LIMIT = int(os.getenv("AGENT_STYLE_CONTEXT_CHAR_LIMIT", "1500"))
CHAT_REPLY_WORD_LIMIT = int(os.getenv("AGENT_CHAT_REPLY_WORD_LIMIT", "35"))
CHAT_ADVICE_REPLY_WORD_LIMIT = int(os.getenv("AGENT_CHAT_ADVICE_REPLY_WORD_LIMIT", "80"))
STYLE_CONTEXT_TYPES = {"whatsapp_chat", "friend_style"}
OPENAI_COMPATIBLE_PROVIDERS = {"deepinfra", "fireworks"}
ONBOARDING_SYSTEM_PROMPT = COMPANION_SYSTEM_PROMPT


class AgentProviderError(RuntimeError):
    pass


def assess_user_message_quality(messages: list[dict[str, str]]) -> dict[str, str | bool]:
    latest_user_message = next(
        (message for message in reversed(messages) if message.get("role") == "user"),
        None,
    )
    if not latest_user_message:
        return {"valid": True}

    text = latest_user_message.get("content", "")
    if _is_greeting_only(text):
        return {"valid": True}

    normalized = _normalized_user_text(text)
    allowed_short_answers = {
        "casual",
        "exploring",
        "longterm",
        "long_term",
        "marriage",
        "yes",
        "yep",
        "yeah",
        "yup",
        "ok",
        "okay",
        "hmm",
        "hm",
        "no",
        "haan",
        "ha",
        "han",
        "nahi",
        "nhi",
        "na",
        "serious",
    }
    vague_answers = {""}
    junk_answers = {"asdf", "qwerty", "test", "knl", "blah", "random"}

    if not normalized:
        return _quality_result("I did not catch that. Could you answer in a few words?")
    if normalized in allowed_short_answers:
        return {"valid": True}
    if normalized in vague_answers:
        return _quality_result("That is a little too vague. Could you say what you mean in one sentence?")
    if normalized in junk_answers:
        return _quality_result("That does not look like a real answer. Could you answer the question directly?")
    if len(normalized) < 2:
        return _quality_result("I did not get enough information. Could you answer with a little more detail?")
    if _looks_like_gibberish(normalized):
        return _quality_result("That looks unclear. Could you rephrase it in normal words?")

    return {"valid": True}


async def generate_agent_reply(
    messages: list[dict[str, str]],
    conversation_id: str | None = None,
    model: str | None = None,
    agent_mode: str = "know_me",
    agent_tone: str = "auto",
    agent_name: str | None = None,
    context_sources: list[dict[str, Any]] | None = None,
    user_profile: dict[str, Any] | None = None,
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
    if provider == "groq":
        return await _groq_chat(
            _system_prompt_with_context(
                ONBOARDING_SYSTEM_PROMPT,
                context_sources,
                agent_mode,
                agent_tone,
                user_profile,
                agent_name,
            ),
            messages,
            conversation_id=conversation_id,
            request_kind=CHAT_REPLY,
            model=model,
        )
    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        return await _openai_compatible_chat(
            provider,
            _system_prompt_with_context(
                ONBOARDING_SYSTEM_PROMPT,
                context_sources,
                agent_mode,
                agent_tone,
                user_profile,
                agent_name,
            ),
            messages,
            conversation_id=conversation_id,
            request_kind=CHAT_REPLY,
            model=model,
        )
    if provider == "ollama":
        return await _ollama_chat(
            _system_prompt_with_context(
                ONBOARDING_SYSTEM_PROMPT,
                context_sources,
                agent_mode,
                agent_tone,
                user_profile,
                agent_name,
            ),
            messages,
            conversation_id=conversation_id,
            request_kind=CHAT_REPLY,
            model=model,
        )
    raise AgentProviderError(f"Unsupported AGENT_PROVIDER: {provider}")


async def extract_profile(
    messages: list[dict[str, str]],
    conversation_id: str | None = None,
    model: str | None = None,
    context_sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    provider = _provider_name()
    logger.info("agent.extract provider=%s user_messages=%s", provider, _user_message_count(messages))
    if provider == "mock":
        _record_usage_event(
            conversation_id=conversation_id,
            request_kind=PROFILE_EXTRACT,
            provider=provider,
            model=model or "mock",
            success=True,
            latency_ms=0,
        )
        return normalize_extracted_profile(_mock_profile(messages), provider)

    profile_messages = _messages_for_profile_extraction(messages)
    extraction_messages = [
        {
            "role": "user",
            "content": _conversation_and_context_text(profile_messages, context_sources),
        }
    ]
    if provider == "groq":
        content = await _groq_chat(
            EXTRACTION_SYSTEM_PROMPT,
            extraction_messages,
            temperature=0,
            conversation_id=conversation_id,
            request_kind=PROFILE_EXTRACT,
            model=model,
        )
    elif provider in OPENAI_COMPATIBLE_PROVIDERS:
        content = await _openai_compatible_chat(
            provider,
            EXTRACTION_SYSTEM_PROMPT,
            extraction_messages,
            temperature=0,
            conversation_id=conversation_id,
            request_kind=PROFILE_EXTRACT,
            model=model,
        )
    elif provider == "ollama":
        content = await _ollama_chat(
            EXTRACTION_SYSTEM_PROMPT,
            extraction_messages,
            temperature=0,
            conversation_id=conversation_id,
            request_kind=PROFILE_EXTRACT,
            model=model,
        )
    else:
        raise AgentProviderError(f"Unsupported AGENT_PROVIDER: {provider}")

    try:
        raw_profile = _parse_json_object(content)
    except (json.JSONDecodeError, AgentProviderError):
        repair_messages = extraction_messages + [{"role": "assistant", "content": content}]
        if provider == "groq":
            content = await _groq_chat(
                EXTRACTION_REPAIR_PROMPT,
                repair_messages,
                temperature=0,
                conversation_id=conversation_id,
                request_kind=PROFILE_EXTRACT_REPAIR,
                model=model,
            )
        elif provider in OPENAI_COMPATIBLE_PROVIDERS:
            content = await _openai_compatible_chat(
                provider,
                EXTRACTION_REPAIR_PROMPT,
                repair_messages,
                temperature=0,
                conversation_id=conversation_id,
                request_kind=PROFILE_EXTRACT_REPAIR,
                model=model,
            )
        else:
            content = await _ollama_chat(
                EXTRACTION_REPAIR_PROMPT,
                repair_messages,
                temperature=0,
                conversation_id=conversation_id,
                request_kind=PROFILE_EXTRACT_REPAIR,
                model=model,
            )
        raw_profile = _parse_json_object(content)

    return normalize_extracted_profile(raw_profile, provider)


async def extract_deep_profile_facts(
    messages: list[dict[str, str]],
    user_id: str,
    conversation_id: str | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    provider = _provider_name()
    logger.info("agent.deep_facts provider=%s user_messages=%s", provider, _user_message_count(messages))
    if provider == "mock":
        _record_usage_event(
            conversation_id=conversation_id,
            request_kind=PROFILE_FACT_EXTRACT,
            provider=provider,
            model=model or "mock",
            success=True,
            latency_ms=0,
        )
        return _mock_deep_profile_facts(messages, user_id, conversation_id)

    extraction_messages = [
        {
            "role": "user",
            "content": _deep_fact_extraction_text(messages),
        }
    ]
    if provider == "groq":
        content = await _groq_chat(
            DEEP_FACT_EXTRACTION_SYSTEM_PROMPT,
            extraction_messages,
            temperature=0,
            conversation_id=conversation_id,
            request_kind=PROFILE_FACT_EXTRACT,
            model=model,
        )
    elif provider in OPENAI_COMPATIBLE_PROVIDERS:
        content = await _openai_compatible_chat(
            provider,
            DEEP_FACT_EXTRACTION_SYSTEM_PROMPT,
            extraction_messages,
            temperature=0,
            conversation_id=conversation_id,
            request_kind=PROFILE_FACT_EXTRACT,
            model=model,
        )
    elif provider == "ollama":
        content = await _ollama_chat(
            DEEP_FACT_EXTRACTION_SYSTEM_PROMPT,
            extraction_messages,
            temperature=0,
            conversation_id=conversation_id,
            request_kind=PROFILE_FACT_EXTRACT,
            model=model,
        )
    else:
        raise AgentProviderError(f"Unsupported AGENT_PROVIDER: {provider}")

    raw = _parse_json_object(content)
    return _normalize_deep_profile_facts(raw, user_id, conversation_id)


async def extract_llm_data_point_candidates(
    extraction_text: str,
    *,
    conversation_id: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    provider = _provider_name()
    logger.info("agent.data_points.extract provider=%s chars=%s", provider, len(extraction_text))
    if provider == "mock":
        _record_usage_event(
            conversation_id=conversation_id,
            request_kind=DATA_POINT_EXTRACT,
            provider=provider,
            model=model or "mock",
            success=True,
            latency_ms=0,
        )
        return _mock_llm_data_points(extraction_text)

    messages = [{"role": "user", "content": extraction_text}]
    if provider == "groq":
        content = await _groq_chat(
            DATA_POINT_EXTRACTION_SYSTEM_PROMPT,
            messages,
            temperature=0,
            conversation_id=conversation_id,
            request_kind=DATA_POINT_EXTRACT,
            model=model,
        )
    elif provider in OPENAI_COMPATIBLE_PROVIDERS:
        content = await _openai_compatible_chat(
            provider,
            DATA_POINT_EXTRACTION_SYSTEM_PROMPT,
            messages,
            temperature=0,
            conversation_id=conversation_id,
            request_kind=DATA_POINT_EXTRACT,
            model=model,
        )
    elif provider == "ollama":
        content = await _ollama_chat(
            DATA_POINT_EXTRACTION_SYSTEM_PROMPT,
            messages,
            temperature=0,
            conversation_id=conversation_id,
            request_kind=DATA_POINT_EXTRACT,
            model=model,
        )
    else:
        raise AgentProviderError(f"Unsupported AGENT_PROVIDER: {provider}")

    return _parse_json_object(content)


async def review_llm_data_point_candidates(
    review_text: str,
    *,
    conversation_id: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    provider = _provider_name()
    logger.info("agent.data_points.review provider=%s chars=%s", provider, len(review_text))
    if provider == "mock":
        _record_usage_event(
            conversation_id=conversation_id,
            request_kind=DATA_POINT_EXTRACT,
            provider=provider,
            model=model or "mock",
            success=True,
            latency_ms=0,
        )
        return _mock_llm_data_point_reviews(review_text)

    messages = [{"role": "user", "content": review_text}]
    if provider == "groq":
        content = await _groq_chat(
            DATA_POINT_REVIEW_SYSTEM_PROMPT,
            messages,
            temperature=0,
            conversation_id=conversation_id,
            request_kind=DATA_POINT_EXTRACT,
            model=model,
        )
    elif provider in OPENAI_COMPATIBLE_PROVIDERS:
        content = await _openai_compatible_chat(
            provider,
            DATA_POINT_REVIEW_SYSTEM_PROMPT,
            messages,
            temperature=0,
            conversation_id=conversation_id,
            request_kind=DATA_POINT_EXTRACT,
            model=model,
        )
    elif provider == "ollama":
        content = await _ollama_chat(
            DATA_POINT_REVIEW_SYSTEM_PROMPT,
            messages,
            temperature=0,
            conversation_id=conversation_id,
            request_kind=DATA_POINT_EXTRACT,
            model=model,
        )
    else:
        raise AgentProviderError(f"Unsupported AGENT_PROVIDER: {provider}")

    return _parse_json_object(content)


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


def _user_message_count(messages: list[dict[str, str]]) -> int:
    return sum(1 for message in messages if message.get("role") == "user")


def _quality_result(reply: str) -> dict[str, str | bool]:
    return {"valid": False, "reply": reply}


def _normalized_user_text(text: str) -> str:
    return " ".join(
        "".join(character.lower() if character.isalnum() else " " for character in text).split()
    )


def _looks_like_gibberish(normalized: str) -> bool:
    compact = normalized.replace(" ", "")
    if not compact:
        return True
    if len(compact) <= 5 and not any(character in "aeiou" for character in compact):
        return True
    if len(set(compact)) <= 2 and len(compact) >= 4:
        return True
    return False


def _previous_prompt_allows_short_confirmation(messages: list[dict[str, str]]) -> bool:
    previous_assistant_message = next(
        (
            message
            for message in reversed(messages[:-1])
            if message.get("role") == "assistant" and message.get("content")
        ),
        None,
    )
    if not previous_assistant_message:
        return False

    prompt = _normalized_user_text(previous_assistant_message.get("content", ""))
    confirmation_markers = {
        "sahi samajh raha hu",
        "sahi samajh raha hun",
        "samajh raha hu",
        "samajh raha hun",
        "right",
        "correct",
        "is that right",
        "does that sound right",
        "am i understanding",
        "did i get that",
    }
    return any(marker in prompt for marker in confirmation_markers)


def _messages_for_profile_extraction(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        message
        for message in messages
        if message.get("quality") != "low_information"
    ]


def _provider_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    provider_messages = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role not in {"assistant", "user", "system"} or content is None:
            continue
        provider_messages.append({"role": role, "content": str(content)})
    if len(provider_messages) <= RECENT_CHAT_MESSAGE_LIMIT:
        return provider_messages

    older_messages = provider_messages[:-RECENT_CHAT_MESSAGE_LIMIT]
    recent_messages = provider_messages[-RECENT_CHAT_MESSAGE_LIMIT:]
    return [_conversation_summary_message(older_messages)] + recent_messages


def _conversation_summary_message(messages: list[dict[str, str]]) -> dict[str, str]:
    user_lines = [
        _truncate_for_context(message["content"], 160)
        for message in messages
        if message["role"] == "user"
    ][-8:]
    assistant_lines = [
        _truncate_for_context(message["content"], 120)
        for message in messages
        if message["role"] == "assistant"
    ][-4:]
    parts = [
        "Earlier conversation summary, compacted locally to save tokens.",
        "Use this only as rough continuity; prefer the recent messages for exact wording.",
    ]
    if user_lines:
        parts.append("Earlier user messages: " + " | ".join(user_lines))
    if assistant_lines:
        parts.append("Earlier assistant prompts: " + " | ".join(assistant_lines))
    return {"role": "system", "content": "\n".join(parts)}


def _system_prompt_with_context(
    system_prompt: str,
    context_sources: list[dict[str, Any]] | None,
    agent_mode: str = "know_me",
    agent_tone: str = "auto",
    user_profile: dict[str, Any] | None = None,
    agent_name: str | None = None,
) -> str:
    return build_companion_system_prompt(
        context_sources=context_sources,
        user_profile=user_profile,
        agent_tone=agent_tone,
        agent_name=agent_name,
        base_prompt=system_prompt,
    )


def _agent_persona_prompt(
    user_profile: dict[str, Any] | None,
    agent_name: str | None = None,
) -> str:
    from agent.behavior import build_companion_behavior

    behavior = build_companion_behavior(user_profile, agent_name=agent_name)
    return behavior_prompt(behavior, user_profile)


def _agent_persona_for_interest(interested_in: str) -> dict[str, str]:
    return agent_persona_for_interest(interested_in)




def _agent_tone_prompt(agent_tone: str) -> str:
    return tone_prompt(agent_tone)


def _conversation_and_context_text(
    messages: list[dict[str, str]],
    context_sources: list[dict[str, Any]] | None,
) -> str:
    conversation_text = "\n".join(
        f"{message['role']}: {message['content']}" for message in messages
    )
    context_text = _context_sources_text(context_sources)
    if not context_text:
        return conversation_text
    return f"{context_text}\n\nConversation:\n{conversation_text}"


def _deep_fact_extraction_text(messages: list[dict[str, str]]) -> str:
    profile_messages = _messages_for_profile_extraction(messages)
    recent_messages = profile_messages[-24:]
    conversation_text = "\n".join(
        f"{message.get('role', 'unknown')}: {message.get('content', '')}"
        for message in recent_messages
        if message.get("content")
    )
    return (
        "Conversation for fact extraction. Extract durable matching facts only from the "
        "user's own words and behavior.\n\n"
        f"{conversation_text}"
    )


def _normalize_deep_profile_facts(
    raw: dict[str, Any],
    user_id: str,
    conversation_id: str | None,
) -> list[dict[str, Any]]:
    raw_facts = raw.get("facts")
    if not isinstance(raw_facts, list):
        return []

    facts = []
    for index, raw_fact in enumerate(raw_facts[:30]):
        if not isinstance(raw_fact, dict):
            continue
        fact = _normalize_deep_profile_fact(raw_fact, user_id, conversation_id, index)
        if fact:
            facts.append(fact)
    return facts


def _normalize_deep_profile_fact(
    raw_fact: dict[str, Any],
    user_id: str,
    conversation_id: str | None,
    index: int,
) -> dict[str, Any] | None:
    category = _snake_key(str(raw_fact.get("category") or "other")) or "other"
    label = str(raw_fact.get("label") or raw_fact.get("key") or "").strip()
    key = _snake_key(str(raw_fact.get("key") or label or f"deep_fact_{index + 1}"))
    if not key or not label:
        return None

    value = raw_fact.get("value")
    if not isinstance(value, dict):
        value = {"kind": key, "detail": str(value or label)}
    value.setdefault("kind", key)

    evidence_text = str(raw_fact.get("evidence") or label).strip()
    confidence = _safe_confidence(raw_fact.get("confidence"), 0.55)
    return {
        "user_id": user_id,
        "category": category[:80],
        "key": key[:120],
        "value": value,
        "label": label[:160],
        "confidence": confidence,
        "source_kind": "agent_deep_memory",
        "source_id": conversation_id,
        "evidence": [
            {
                "conversation_id": conversation_id,
                "message_index": None,
                "text": evidence_text[:320],
            }
        ],
        "status": "active",
        "visibility": "internal",
        "used_for_matching": True,
    }


def _snake_key(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")


def _safe_confidence(value: Any, fallback: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = fallback
    return max(0.0, min(0.95, confidence))


def _context_sources_text(context_sources: list[dict[str, Any]] | None) -> str:
    return context_sources_text(context_sources)


def _truncate_for_context(text: str, limit: int) -> str:
    return truncate_for_context(text, limit)


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
            if error.response is not None:
                raw_usage["rate_limit"] = _provider_rate_limit_headers(error.response)
                try:
                    raw_usage["error"] = error.response.json()
                except ValueError:
                    raw_usage["error_text"] = error.response.text[:500]
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


def _deepinfra_api_key() -> str:
    return os.getenv("DEEPINFRA_API_KEY") or os.getenv("DEEPINFRA_TOKEN") or ""


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


def _parse_json_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        raise AgentProviderError("Model did not return a JSON object.")
    return json.loads(cleaned[start : end + 1])


def _mock_reply(
    messages: list[dict[str, str]],
    user_profile: dict[str, Any] | None = None,
    agent_name: str | None = None,
) -> str:
    user_messages = [message for message in messages if message["role"] == "user"]
    persona = _agent_persona_for_interest(str((user_profile or {}).get("interested_in") or ""))
    if agent_name and agent_name.strip():
        persona = {**persona, "name": agent_name.strip()}
    if user_messages and _is_greeting_only(user_messages[-1]["content"]):
        return f"Hey, I'm {persona['name']}. Chill, we can talk normally first."

    prompts = [
        "hmm okay, fair.",
        "haan, that feels clear.",
        "acha, got it.",
        "fair enough, I like that honestly.",
        "sahi hai, keep going.",
    ]
    return prompts[min(len(user_messages), len(prompts) - 1)]


def _mock_deep_profile_facts(
    messages: list[dict[str, str]],
    user_id: str,
    conversation_id: str | None,
) -> list[dict[str, Any]]:
    text = " ".join(
        str(message.get("content", "")).lower()
        for message in _messages_for_profile_extraction(messages)
        if message.get("role") == "user"
    )
    raw_facts = []
    if "career" in text or "growth" in text:
        raw_facts.append(
            {
                "category": "goals",
                "key": "career_growth",
                "label": "Values career growth",
                "value": {
                    "kind": "career_growth",
                    "detail": "User repeatedly mentions career or growth.",
                },
                "confidence": 0.72,
                "evidence": "Mentions career or growth as important.",
            }
        )
    if "respect" in text:
        raw_facts.append(
            {
                "category": "values",
                "key": "mutual_respect",
                "label": "Values mutual respect",
                "value": {"kind": "mutual_respect"},
                "confidence": 0.74,
                "evidence": "Mentions mutual respect.",
            }
        )
    if not raw_facts:
        raw_facts.append(
            {
                "category": "personality",
                "key": "open_to_reflection",
                "label": "Open to reflection",
                "value": {"kind": "open_to_reflection"},
                "confidence": 0.42,
                "evidence": "Continues the onboarding conversation.",
            }
        )
    return _normalize_deep_profile_facts({"facts": raw_facts}, user_id, conversation_id)


def _mock_llm_data_points(extraction_text: str) -> dict[str, Any]:
    text = extraction_text.lower()
    points: list[dict[str, Any]] = []
    if "coffee" in text and "walk" in text:
        points.append(
            {
                "category": "recent_events",
                "key": "coffee_then_walk_plan",
                "label": "Planned coffee then a walk",
                "meaning": "Useful when the user asks what the latest concrete WhatsApp plan was.",
                "value": {"kind": "coffee_then_walk_plan", "detail": "Coffee first, then walk."},
                "confidence": 0.82,
                "evidence": ["coffee first, then walk?"],
                "used_for_chat_context": True,
                "used_for_matching": False,
                "used_for_style": False,
                "privacy_level": "normal",
            }
        )
    if "wahi per rukna" in text or "location" in text:
        points.append(
            {
                "category": "conversation_context",
                "key": "meeting_location_coordination",
                "label": "Coordinated where to wait or meet",
                "meaning": "Useful for answering questions about last WhatsApp location or meeting context.",
                "value": {"kind": "meeting_location_coordination"},
                "confidence": 0.78,
                "evidence": ["wahi per rukna", "location kidhar hai"],
                "used_for_chat_context": True,
                "used_for_matching": False,
                "used_for_style": False,
                "privacy_level": "normal",
            }
        )
    if not points:
        points.append(
            {
                "category": "communication_style",
                "key": "short_casual_whatsapp_style",
                "label": "Uses short casual WhatsApp replies",
                "meaning": "Useful for adapting reply length and rhythm.",
                "value": {"kind": "short_casual_whatsapp_style"},
                "confidence": 0.58,
                "evidence": ["short chat messages"],
                "used_for_chat_context": True,
                "used_for_matching": False,
                "used_for_style": True,
                "privacy_level": "normal",
            }
        )
    return {"data_points": points}


def _mock_llm_data_point_reviews(review_text: str) -> dict[str, Any]:
    try:
        payload = _parse_json_object(review_text)
        candidates = payload.get("candidates") if isinstance(payload, dict) else []
    except Exception:
        candidates = []
    reviews: list[dict[str, Any]] = []
    for candidate in candidates if isinstance(candidates, list) else []:
        if not isinstance(candidate, dict):
            continue
        key = str(candidate.get("key") or "")
        label = str(candidate.get("label") or "")
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), list) else []
        if "talked about" in label.lower() or not evidence:
            reviews.append(
                {
                    "candidate_key": key,
                    "decision": "reject",
                    "what_we_learned": "",
                    "why_it_matters": "",
                    "confidence": 0.0,
                    "evidence": [],
                    "usage": {"debug_only": True},
                    "final_point": None,
                    "rejection_reason": "Weak keyword-style candidate.",
                }
            )
            continue
        reviews.append(
            {
                "candidate_key": key,
                "decision": "approve",
                "what_we_learned": label,
                "why_it_matters": str(candidate.get("meaning") or "Useful later."),
                "confidence": candidate.get("confidence") or 0.72,
                "evidence": evidence[:3],
                "usage": candidate.get("usage") or {"chat_context": True},
                "final_point": {
                    "category": candidate.get("category") or "conversation_context",
                    "key": key,
                    "label": label,
                    "meaning": candidate.get("meaning") or "Useful later.",
                    "value": candidate.get("value") or {"kind": key},
                    "privacy_level": "normal",
                },
                "rejection_reason": None,
            }
        )
    return {"reviews": reviews}


def _compact_chat_reply(content: str, messages: list[dict[str, str]]) -> str:
    cleaned = " ".join(content.strip().split())
    if not cleaned:
        return cleaned

    limit = _chat_reply_word_limit(messages)
    words = cleaned.split()
    if len(words) <= limit:
        return cleaned

    sentence_parts = re.split(r"(?<=[.!?।])\s+", cleaned)
    kept: list[str] = []
    count = 0
    for sentence in sentence_parts:
        sentence_words = sentence.split()
        if not sentence_words:
            continue
        if kept and count + len(sentence_words) > limit:
            break
        kept.append(sentence)
        count += len(sentence_words)
        if count >= limit:
            break

    compact = " ".join(kept).strip()
    if compact:
        return compact
    return " ".join(words[:limit]).rstrip(" ,;:")


def _chat_reply_word_limit(messages: list[dict[str, str]]) -> int:
    latest_user_text = _latest_user_text(messages)
    advice_markers = {
        "advice",
        "detail",
        "explain",
        "help",
        "how",
        "plan",
        "suggest",
        "why",
    }
    if any(marker in latest_user_text for marker in advice_markers):
        return CHAT_ADVICE_REPLY_WORD_LIMIT
    return CHAT_REPLY_WORD_LIMIT


def _latest_user_text(messages: list[dict[str, str]]) -> str:
    latest = next(
        (
            message.get("content", "")
            for message in reversed(messages)
            if message.get("role") == "user"
        ),
        "",
    )
    return _normalized_user_text(str(latest))


def _is_greeting_only(text: str) -> bool:
    normalized = text.strip().lower().strip(".!?, ")
    return normalized in {"hi", "hello", "hey", "hii", "heyy", "namaste"}


def _mock_profile(messages: list[dict[str, str]]) -> dict[str, Any]:
    profile_messages = _messages_for_profile_extraction(messages)
    text = " ".join(
        message["content"].lower()
        for message in profile_messages
        if message["role"] == "user"
    )
    city = "Bengaluru" if "bengaluru" in text or "bangalore" in text else "unknown"
    intent = "marriage" if "marriage" in text else "long_term" if "long" in text else "unknown"
    dealbreakers = []
    if "smoking" in text or "smoker" in text:
        dealbreakers.append("smoking")

    return {
        "agent_provider": _provider_name(),
        "display_name": None,
        "age": None,
        "city": {"value": city, "source": "user_stated" if city != "unknown" else "unknown", "confidence": 0.7},
        "relationship_intent": {
            "value": intent,
            "source": "user_stated" if intent != "unknown" else "unknown",
            "confidence": 0.75,
        },
        "values": {
            "values": ["family", "emotional_stability"],
            "source": "inferred",
            "confidence": 0.55,
        },
        "lifestyle": {"values": [], "source": "unknown", "confidence": 0.4},
        "communication_style": {
            "value": "direct",
            "source": "inferred",
            "confidence": 0.5,
        },
        "family_expectations": {
            "value": "unknown",
            "source": "unknown",
            "confidence": 0.4,
        },
        "children_preference": {
            "value": "unknown",
            "source": "unknown",
            "confidence": 0.4,
        },
        "dealbreakers": {
            "values": dealbreakers,
            "source": "user_stated" if dealbreakers else "unknown",
            "confidence": 0.65,
        },
        "soft_preferences": {"values": [], "source": "unknown", "confidence": 0.4},
        "summary": "Draft profile extracted from the Omiryn onboarding conversation.",
    }
