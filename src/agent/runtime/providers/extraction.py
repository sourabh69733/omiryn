from __future__ import annotations

import json
import logging
from typing import Any

from agent.memory_engine.extraction.prompts import (
    DATA_POINT_EXTRACTION_SYSTEM_PROMPT,
    DATA_POINT_REVIEW_SYSTEM_PROMPT,
    DEEP_FACT_EXTRACTION_SYSTEM_PROMPT,
)
from agent.profile_engine.extraction import normalize_extracted_profile
from agent.profile_engine.prompts import EXTRACTION_REPAIR_PROMPT, EXTRACTION_SYSTEM_PROMPT
from agent.runtime.usage import DATA_POINT_EXTRACT, PROFILE_EXTRACT, PROFILE_EXTRACT_REPAIR, PROFILE_FACT_EXTRACT

from .config import _provider_name
from .errors import AgentProviderError
from .json_utils import _parse_json_object
from .messages import _conversation_and_context_text, _messages_for_profile_extraction, _user_message_count
from .mock import _mock_deep_profile_facts, _mock_llm_data_point_reviews, _mock_llm_data_points, _mock_profile
from .normalization import _deep_fact_extraction_text, _normalize_deep_profile_facts
from .router import provider_chat
from .usage_events import _record_usage_event

logger = logging.getLogger(__name__)


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
    content = await provider_chat(
        provider=provider,
        system_prompt=EXTRACTION_SYSTEM_PROMPT,
        messages=extraction_messages,
        temperature=0,
        conversation_id=conversation_id,
        request_kind=PROFILE_EXTRACT,
        model=model,
    )

    try:
        raw_profile = _parse_json_object(content)
    except (json.JSONDecodeError, AgentProviderError):
        repair_messages = extraction_messages + [{"role": "assistant", "content": content}]
        content = await provider_chat(
            provider=provider,
            system_prompt=EXTRACTION_REPAIR_PROMPT,
            messages=repair_messages,
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
    content = await provider_chat(
        provider=provider,
        system_prompt=DEEP_FACT_EXTRACTION_SYSTEM_PROMPT,
        messages=extraction_messages,
        temperature=0,
        conversation_id=conversation_id,
        request_kind=PROFILE_FACT_EXTRACT,
        model=model,
    )

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
    content = await provider_chat(
        provider=provider,
        system_prompt=DATA_POINT_EXTRACTION_SYSTEM_PROMPT,
        messages=messages,
        temperature=0,
        conversation_id=conversation_id,
        request_kind=DATA_POINT_EXTRACT,
        model=model,
    )

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
    content = await provider_chat(
        provider=provider,
        system_prompt=DATA_POINT_REVIEW_SYSTEM_PROMPT,
        messages=messages,
        temperature=0,
        conversation_id=conversation_id,
        request_kind=DATA_POINT_EXTRACT,
        model=model,
    )

    return _parse_json_object(content)
