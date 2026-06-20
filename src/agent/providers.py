from __future__ import annotations

import json
import logging
import os
import re
from time import perf_counter
from typing import Any

import httpx

from agent.extraction import normalize_extracted_profile
from agent.usage import (
    CHAT_REPLY,
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

ONBOARDING_SYSTEM_PROMPT = """You are Omiryn's private dating companion.
Your job is to talk naturally, make the user feel less alone, and slowly understand
them well enough to help them find a real-world match.

Behavior:
- Read the conversation before replying. Do not follow a fixed questionnaire.
- Default to one short WhatsApp-like reply. Use 1 sentence unless the user asks for detail.
- Match the user's message length. If they say "yes", "hmm", or one line, answer briefly.
- Do not ask a question every turn. Sometimes react, joke lightly, reassure, or share a small opinion.
- Ask at most one soft question when it feels natural.
- Learn the user's personality, choices, and partner preferences gradually through normal conversation.
- Avoid repeating the same question pattern or validation phrases.
- Do not summarize the user every turn.
- Avoid phrases like "I'm learning your pattern", "this helps build your profile", or "compatibility signals".
- Never write a long paragraph in normal chat.
- Do not flirt, roleplay as a partner, or pretend to be a match.
- You may feel like a friendly girl/boy companion based on persona, but be honest you are an AI if asked.

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

DEEP_FACT_EXTRACTION_SYSTEM_PROMPT = """Extract private Omiryn matching memory facts from the conversation.
Return only valid JSON. Do not include markdown.
Use this shape:
{
  "facts": [
    {
      "category": "values",
      "key": "mutual_respect",
      "label": "Values mutual respect",
      "value": {"kind": "mutual_respect", "detail": "Short detail"},
      "confidence": 0.72,
      "evidence": "Short user quote or paraphrase"
    }
  ]
}
Rules:
- Extract only facts about the user, not the assistant or other people.
- Prefer many small facts over broad summaries.
- Useful categories: dating_intent, values, lifestyle, communication, conflict_style,
  attachment_style, emotional_patterns, family_context, partner_preferences,
  dealbreakers, attraction_patterns, goals, constraints, personality.
- Do not invent. If weakly inferred, confidence must be <= 0.45.
- Do not diagnose medical or mental health conditions.
- Keep labels under 12 words and evidence under 30 words.
- Return at most 25 facts."""


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
        return _mock_reply(messages, user_profile)
    if provider == "groq":
        return await _groq_chat(
            _system_prompt_with_context(
                ONBOARDING_SYSTEM_PROMPT,
                context_sources,
                agent_mode,
                agent_tone,
                user_profile,
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
    return provider_messages


def _system_prompt_with_context(
    system_prompt: str,
    context_sources: list[dict[str, Any]] | None,
    agent_mode: str = "know_me",
    agent_tone: str = "auto",
    user_profile: dict[str, Any] | None = None,
) -> str:
    context_text = _context_sources_text(context_sources)
    persona_text = _agent_persona_prompt(user_profile)
    mode_text = _agent_mode_prompt(agent_mode)
    tone_text = _agent_tone_prompt(agent_tone)
    if not context_text:
        return f"{system_prompt}\n\n{persona_text}\n\n{mode_text}\n\n{tone_text}"
    return (
        f"{system_prompt}\n\n{persona_text}\n\n{mode_text}\n\n{tone_text}\n\n"
        "Additional user-provided context is available below. Use it only to ask better "
        "questions, understand the user, and lightly adapt tone when speaking-style context "
        "is present. If WhatsApp context is present, you may discuss broad recent topics from "
        "the processed summary, but be clear you do not have live WhatsApp access or a full "
        "raw transcript. If a friend-style text profile is present, use it only as a writing-style "
        "reference for rhythm, warmth, brevity, and phrasing. Reply directly in that style without "
        "reintroducing yourself as Omiryn unless the user asks who you are. Never claim to be that "
        "friend, never roleplay as that person, and never imply they wrote or approved your reply. "
        "If the selected friend-style context is missing, ambiguous, or clearly for the wrong sender, "
        "ask which sender/style the user wants to use. Mention imported context only when it is useful "
        "or the user asks. Do not quote private source text back unless the user explicitly asks.\n"
        f"{context_text}"
    )


def _agent_persona_prompt(user_profile: dict[str, Any] | None) -> str:
    gender = (user_profile or {}).get("gender") or "unknown"
    interested_in = (user_profile or {}).get("interested_in") or "unknown"
    display_name = (user_profile or {}).get("display_name") or "unknown"
    email = (user_profile or {}).get("email") or "unknown"
    location = (user_profile or {}).get("location") or "India"
    country = (user_profile or {}).get("country") or "India"
    timezone = (user_profile or {}).get("timezone") or "Asia/Kolkata"
    current_date = (user_profile or {}).get("current_date") or "unknown"
    current_time = (user_profile or {}).get("current_time") or "unknown"
    current_weekday = (user_profile or {}).get("current_weekday") or "unknown"
    persona = _agent_persona_for_interest(str(interested_in))
    return (
        f"User identity: display_name={display_name}, email={email}.\n"
        f"User basics: gender={gender}, interested_in={interested_in}, "
        f"location={location}, country={country}.\n"
        f"Current context: date={current_date}, time={current_time}, "
        f"weekday={current_weekday}, timezone={timezone}.\n"
        f"Agent persona: name={persona['name']}, presentation={persona['presentation']}.\n"
        "Use identity/location/time only when naturally helpful. Do not mention the user's email "
        "unless they ask about account details. If location is only a default, treat it as uncertain. "
        "Speak from this persona in a casual WhatsApp-like way. Use small replies, not big paragraphs. "
        "Do not keep saying your name. Do not turn every reply into a dating interview. "
        "Do not repeat the same supportive line again and again."
    )


def _agent_persona_for_interest(interested_in: str) -> dict[str, str]:
    if interested_in == "women":
        return {"name": "Annie", "presentation": "girl/woman companion"}
    if interested_in == "men":
        return {"name": "Arjun", "presentation": "boy/man companion"}
    return {"name": "Mira", "presentation": "warm neutral companion"}


def _agent_mode_prompt(agent_mode: str) -> str:
    prompts = {
        "know_me": (
            "Current agent mode: Companion. Talk normally first. Quietly learn the user's "
            "personality, values, lifestyle, communication style, and relationship goals over time. "
            "Let the conversation breathe; do not force a profile question every turn."
        ),
        "coach_me": (
            "Current agent mode: Coach me. Help the user reflect on patterns and choices. "
            "Be practical, kind, and direct. Avoid therapy claims or diagnosis."
        ),
        "match_me": (
            "Current agent mode: Match me. Focus on what partner traits, relationship dynamics, "
            "and compatibility signals may fit the user. Explain uncertainty clearly."
        ),
        "talk_like_me": (
            "Current agent mode: Talk like me. Prioritize mirroring the user's pacing, wording, "
            "and conversational energy from imported speaking-style context while staying respectful."
        ),
    }
    return prompts.get(agent_mode, prompts["know_me"])


def _agent_tone_prompt(agent_tone: str) -> str:
    prompts = {
        "auto": (
            "Tone setting: Auto. Match the user's natural tone from recent messages and imported "
            "speaking-style context. If signals conflict, stay warm, clear, brief, and natural."
        ),
        "casual": "Tone setting: Casual. Use relaxed, simple language without sounding sloppy.",
        "warm": "Tone setting: Warm. Be gentle, supportive, and emotionally clear.",
        "formal": "Tone setting: Formal. Be polished, structured, and respectful.",
        "direct": "Tone setting: Direct. Be concise, specific, and low-fluff.",
        "playful": "Tone setting: Playful. Be light and witty while staying respectful.",
    }
    return prompts.get(agent_tone, prompts["auto"])


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
    if not context_sources:
        return ""
    sections = []
    for source in context_sources[:CONTEXT_SOURCE_LIMIT]:
        title = source.get("title") or "Untitled source"
        source_type = source.get("source_type") or "context"
        content_limit = (
            STYLE_CONTEXT_CHAR_LIMIT
            if source_type in STYLE_CONTEXT_TYPES
            else CONTEXT_SOURCE_CHAR_LIMIT
        )
        content = _truncate_for_context(str(source.get("content") or ""), content_limit)
        sections.append(f"[{source_type}] {title}\n{content}")
    return "User-provided context sources:\n" + "\n\n".join(sections)


def _truncate_for_context(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


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
        "messages": [{"role": "system", "content": system_prompt}] + _provider_messages(messages),
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
            raw_usage = {
                **usage,
                "rate_limit": _groq_rate_limit_headers(response),
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
            raw_usage = {}
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
    payload = {
        "model": model or os.getenv("OLLAMA_MODEL", "llama3.1"),
        "messages": [{"role": "system", "content": system_prompt}] + _provider_messages(messages),
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


def _mock_reply(
    messages: list[dict[str, str]],
    user_profile: dict[str, Any] | None = None,
) -> str:
    user_messages = [message for message in messages if message["role"] == "user"]
    persona = _agent_persona_for_interest(str((user_profile or {}).get("interested_in") or ""))
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
