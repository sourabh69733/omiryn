from __future__ import annotations

import json
import os
from typing import Any

import httpx

from agent.extraction import normalize_extracted_profile

ONBOARDING_SYSTEM_PROMPT = """You are Omiryn's matchmaking agent.
You help users build a private relationship profile for better matching.
Ask one concise question at a time. Do not flirt. Do not pretend to be a match.
Focus on intent, values, lifestyle, communication style, family expectations,
children preference, location constraints, and dealbreakers."""

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


async def generate_agent_reply(messages: list[dict[str, str]]) -> str:
    provider = _provider_name()
    if provider == "mock":
        return _mock_reply(messages)
    if provider == "groq":
        return await _groq_chat(ONBOARDING_SYSTEM_PROMPT, messages)
    if provider == "ollama":
        return await _ollama_chat(ONBOARDING_SYSTEM_PROMPT, messages)
    raise AgentProviderError(f"Unsupported AGENT_PROVIDER: {provider}")


async def extract_profile(messages: list[dict[str, str]]) -> dict[str, Any]:
    provider = _provider_name()
    if provider == "mock":
        return normalize_extracted_profile(_mock_profile(messages), provider)

    extraction_messages = [
        {
            "role": "user",
            "content": "\n".join(
                f"{message['role']}: {message['content']}" for message in messages
            ),
        }
    ]
    if provider == "groq":
        content = await _groq_chat(EXTRACTION_SYSTEM_PROMPT, extraction_messages, temperature=0)
    elif provider == "ollama":
        content = await _ollama_chat(EXTRACTION_SYSTEM_PROMPT, extraction_messages, temperature=0)
    else:
        raise AgentProviderError(f"Unsupported AGENT_PROVIDER: {provider}")

    try:
        raw_profile = _parse_json_object(content)
    except (json.JSONDecodeError, AgentProviderError):
        repair_messages = extraction_messages + [{"role": "assistant", "content": content}]
        if provider == "groq":
            content = await _groq_chat(EXTRACTION_REPAIR_PROMPT, repair_messages, temperature=0)
        else:
            content = await _ollama_chat(EXTRACTION_REPAIR_PROMPT, repair_messages, temperature=0)
        raw_profile = _parse_json_object(content)

    return normalize_extracted_profile(raw_profile, provider)


def _provider_name() -> str:
    return os.getenv("AGENT_PROVIDER", "mock").strip().lower()


async def _groq_chat(
    system_prompt: str,
    messages: list[dict[str, str]],
    temperature: float = 0.4,
) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise AgentProviderError("GROQ_API_KEY is required when AGENT_PROVIDER=groq.")

    payload = {
        "model": os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "temperature": temperature,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


async def _ollama_chat(
    system_prompt: str,
    messages: list[dict[str, str]],
    temperature: float = 0.4,
) -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    payload = {
        "model": os.getenv("OLLAMA_MODEL", "llama3.1"),
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "stream": False,
        "options": {"temperature": temperature},
    }

    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(f"{base_url}/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"]


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
    prompts = [
        "Are you looking for long-term dating, marriage, exploring, or something else?",
        "What values matter most to you in a partner?",
        "What kind of communication makes you feel respected during conflict?",
        "What are your hard dealbreakers?",
        "How should family, children, and location fit into your future relationship?",
    ]
    return prompts[min(len(user_messages), len(prompts) - 1)]


def _mock_profile(messages: list[dict[str, str]]) -> dict[str, Any]:
    text = " ".join(message["content"].lower() for message in messages if message["role"] == "user")
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
