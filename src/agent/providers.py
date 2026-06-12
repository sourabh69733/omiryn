from __future__ import annotations

import json
import logging
import os
from time import perf_counter
from typing import Any

import httpx

from agent.extraction import normalize_extracted_profile
from storage import save_agent_usage_event

logger = logging.getLogger(__name__)

ONBOARDING_SYSTEM_PROMPT = """You are Omiryn's private matchmaking interviewer.
Your job is to understand the user well enough to build a structured dating profile
for real-world matching.

Behavior:
- Read the full conversation before replying. Do not follow a fixed questionnaire.
- Keep replies warm, natural, and short: usually 1-3 sentences.
- Ask only one clear question at a time.
- If the user only greets you, greets back briefly and ask the first useful question.
- If the user gives a vague answer, ask a focused follow-up before moving on.
- If the user answers clearly, acknowledge the answer in a few words and ask the next missing topic.
- Do not repeat questions that the user has already answered.
- Do not flirt, roleplay as a partner, or pretend to be a match.

Collect these topics over time:
relationship intent, values, lifestyle, communication style, conflict style,
family expectations, children preference, location constraints, attraction preferences,
and hard dealbreakers."""

EXTRACTION_REPAIR_PROMPT = """Your previous response was not valid JSON for Omiryn.
Return only one JSON object. No markdown, no commentary, no extra text."""

EXTRACTION_SYSTEM_PROMPT = """Extract a structured dating profile from this conversation.
Return only valid JSON. Do not include markdown.
Use this shape:
{
  "display_name": null,
  "age": null,
  "city": {"value": "unknown", "source": "unknown", "confidence": 0.5},
  "relationship_intent": {"value": "unknown", "source": "unknown", "confidence": 0.5},
  "values": {"values": [], "source": "unknown", "confidence": 0.5},
  "lifestyle": {"values": [], "source": "unknown", "confidence": 0.5},
  "communication_style": {"value": "unknown", "source": "unknown", "confidence": 0.5},
  "family_expectations": {"value": "unknown", "source": "unknown", "confidence": 0.5},
  "children_preference": {"value": "unknown", "source": "unknown", "confidence": 0.5},
  "dealbreakers": {"values": [], "source": "unknown", "confidence": 0.5},
  "soft_preferences": {"values": [], "source": "unknown", "confidence": 0.5},
  "summary": ""
}
For every source use one of: user_stated, inferred, unknown.
Rules:
- If the user did not clearly state a field, use source=inferred only when there is strong evidence.
- Otherwise use value="unknown", source="unknown", confidence <= 0.5.
- Do not invent age, city, religion, family preference, children preference, or dealbreakers.
- Keep values and lifestyle as short snake_case strings.
- Keep summary under 40 words."""


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
        "serious",
    }
    vague_answers = {"idk", "dont know", "don't know", "maybe", "yes", "no", "ok", "okay"}
    junk_answers = {"asdf", "qwerty", "test", "knl", "blah", "random"}

    if not normalized:
        return _quality_result("I did not catch that. Could you answer in a few words?")
    if normalized in allowed_short_answers:
        return {"valid": True}
    if normalized in vague_answers:
        return _quality_result("That is a little too vague. Could you say what you mean in one sentence?")
    if normalized in junk_answers:
        return _quality_result("That does not look like a real answer. Could you answer the question directly?")
    if len(normalized) < 4:
        return _quality_result("I did not get enough information. Could you answer with a little more detail?")
    if _looks_like_gibberish(normalized):
        return _quality_result("That looks unclear. Could you rephrase it in normal words?")

    return {"valid": True}


async def generate_agent_reply(
    messages: list[dict[str, str]],
    conversation_id: str | None = None,
    model: str | None = None,
    context_sources: list[dict[str, Any]] | None = None,
) -> str:
    provider = _provider_name()
    logger.info("agent.reply provider=%s user_messages=%s", provider, _user_message_count(messages))
    quality = assess_user_message_quality(messages)
    if not quality["valid"]:
        _record_usage_event(
            conversation_id=conversation_id,
            request_kind="input_guardrail",
            provider="guardrail",
            model="local",
            success=True,
            latency_ms=0,
        )
        return str(quality["reply"])

    if provider == "mock":
        _record_usage_event(
            conversation_id=conversation_id,
            request_kind="chat_reply",
            provider=provider,
            model=model or "mock",
            success=True,
            latency_ms=0,
        )
        return _mock_reply(messages)
    if provider == "groq":
        return await _groq_chat(
            _system_prompt_with_context(ONBOARDING_SYSTEM_PROMPT, context_sources),
            messages,
            conversation_id=conversation_id,
            request_kind="chat_reply",
            model=model,
        )
    if provider == "ollama":
        return await _ollama_chat(
            _system_prompt_with_context(ONBOARDING_SYSTEM_PROMPT, context_sources),
            messages,
            conversation_id=conversation_id,
            request_kind="chat_reply",
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
            request_kind="profile_extract",
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
            request_kind="profile_extract",
            model=model,
        )
    elif provider == "ollama":
        content = await _ollama_chat(
            EXTRACTION_SYSTEM_PROMPT,
            extraction_messages,
            temperature=0,
            conversation_id=conversation_id,
            request_kind="profile_extract",
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
                request_kind="profile_extract_repair",
                model=model,
            )
        else:
            content = await _ollama_chat(
                EXTRACTION_REPAIR_PROMPT,
                repair_messages,
                temperature=0,
                conversation_id=conversation_id,
                request_kind="profile_extract_repair",
                model=model,
            )
        raw_profile = _parse_json_object(content)

    return normalize_extracted_profile(raw_profile, provider)


def _provider_name() -> str:
    return os.getenv("AGENT_PROVIDER", "mock").strip().lower()


def agent_runtime_status() -> dict[str, Any]:
    provider = _provider_name()
    return {
        "provider": provider,
        "model": _provider_model(provider),
        "available_models": _available_models(provider),
        "groq_api_key_loaded": bool(os.getenv("GROQ_API_KEY")),
        "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    }


def _provider_model(provider: str) -> str | None:
    if provider == "groq":
        return os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
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
    if provider == "ollama":
        return _models_from_env("OLLAMA_AVAILABLE_MODELS", [os.getenv("OLLAMA_MODEL", "llama3.1")])
    if provider == "mock":
        return ["mock"]
    return []


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


def _messages_for_profile_extraction(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        message
        for message in messages
        if message.get("quality") != "low_information"
    ]


def _system_prompt_with_context(
    system_prompt: str,
    context_sources: list[dict[str, Any]] | None,
) -> str:
    context_text = _context_sources_text(context_sources)
    if not context_text:
        return system_prompt
    return (
        f"{system_prompt}\n\n"
        "Additional user-provided context is available below. Use it only to ask better "
        "questions, understand the user, and lightly adapt tone when speaking-style context "
        "is present. Do not quote private source text back unless the user explicitly asks.\n"
        f"{context_text}"
    )


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


def _context_sources_text(context_sources: list[dict[str, Any]] | None) -> str:
    if not context_sources:
        return ""
    sections = []
    for source in context_sources[:5]:
        title = source.get("title") or "Untitled source"
        source_type = source.get("source_type") or "context"
        content = str(source.get("content") or "")[:4000]
        sections.append(f"[{source_type}] {title}\n{content}")
    return "User-provided context sources:\n" + "\n\n".join(sections)


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

    payload = {
        "model": model or os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "temperature": temperature,
    }
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
            _record_usage_event(
                conversation_id=conversation_id,
                request_kind=request_kind,
                provider="groq",
                model=payload["model"],
                success=True,
                latency_ms=latency_ms,
                raw_usage=usage,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
            )
            return data["choices"][0]["message"]["content"]
        except Exception as error:
            _record_usage_event(
                conversation_id=conversation_id,
                request_kind=request_kind,
                provider="groq",
                model=payload["model"],
                success=False,
                latency_ms=_elapsed_ms(started_at),
                error=str(error),
            )
            raise


async def _ollama_chat(
    system_prompt: str,
    messages: list[dict[str, str]],
    temperature: float = 0.4,
    conversation_id: str | None = None,
    request_kind: str = "chat_reply",
    model: str | None = None,
) -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    payload = {
        "model": model or os.getenv("OLLAMA_MODEL", "llama3.1"),
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "stream": False,
        "options": {"temperature": temperature},
    }

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
                raw_usage=data,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=_sum_optional_ints(prompt_tokens, completion_tokens),
            )
            return data["message"]["content"]
        except Exception as error:
            _record_usage_event(
                conversation_id=conversation_id,
                request_kind=request_kind,
                provider="ollama",
                model=payload["model"],
                success=False,
                latency_ms=_elapsed_ms(started_at),
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


def _estimated_cost_usd(
    provider: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float | None:
    if provider != "groq" or prompt_tokens is None or completion_tokens is None:
        return None

    input_cost_per_1m = float(os.getenv("GROQ_INPUT_COST_PER_1M", "0") or 0)
    output_cost_per_1m = float(os.getenv("GROQ_OUTPUT_COST_PER_1M", "0") or 0)
    if input_cost_per_1m == 0 and output_cost_per_1m == 0:
        return None

    return round(
        (prompt_tokens / 1_000_000 * input_cost_per_1m)
        + (completion_tokens / 1_000_000 * output_cost_per_1m),
        8,
    )


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


def _mock_reply(messages: list[dict[str, str]]) -> str:
    user_messages = [message for message in messages if message["role"] == "user"]
    if user_messages and _is_greeting_only(user_messages[-1]["content"]):
        return (
            "Hi, good to meet you. Are you looking for long-term dating, marriage, "
            "exploring, or something else?"
        )

    prompts = [
        "Are you looking for long-term dating, marriage, exploring, or something else?",
        "What values matter most to you in a partner?",
        "What kind of communication makes you feel respected during conflict?",
        "What are your hard dealbreakers?",
        "How should family, children, and location fit into your future relationship?",
    ]
    return prompts[min(len(user_messages), len(prompts) - 1)]


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
