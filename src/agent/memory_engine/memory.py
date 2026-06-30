from __future__ import annotations

import logging
import os

from agent.memory_engine.data_point_extraction import (
    capture_hybrid_conversation_data_points,
    should_run_hybrid_data_point_review,
)
from agent.memory_engine.data_points import normalize_data_point
from agent.memory_engine.profile_facts import extract_profile_facts_from_message
from agent.runtime.providers import extract_deep_profile_facts
from storage import upsert_profile_fact

logger = logging.getLogger(__name__)
DEEP_FACT_EXTRACTION_INTERVAL = int(os.getenv("PROFILE_FACT_DEEP_EXTRACT_INTERVAL", "5"))


def deep_fact_extraction_interval() -> int:
    try:
        return int(os.getenv("PROFILE_FACT_DEEP_EXTRACT_INTERVAL", str(DEEP_FACT_EXTRACTION_INTERVAL)))
    except ValueError:
        return DEEP_FACT_EXTRACTION_INTERVAL


def capture_profile_facts_from_user_message(
    conversation_id: str,
    user_id: str | None,
    message: str,
    message_index: int,
    quality_valid: bool,
) -> None:
    if not user_id or not quality_valid:
        return

    facts = extract_profile_facts_from_message(
        user_id,
        conversation_id,
        message,
        message_index,
    )
    for fact in facts:
        upsert_profile_fact(normalize_data_point(fact))


def should_run_deep_profile_fact_extraction(
    user_id: str | None,
    messages: list[dict[str, object]],
    quality_valid: bool,
) -> bool:
    interval = deep_fact_extraction_interval()
    if not user_id or not quality_valid or interval <= 0:
        return False
    valid_user_messages = sum(
        1
        for message in messages
        if message.get("role") == "user" and message.get("quality") != "low_information"
    )
    return valid_user_messages > 0 and valid_user_messages % interval == 0


async def capture_deep_profile_facts_from_conversation(
    conversation_id: str,
    user_id: str,
    messages: list[dict[str, object]],
    model: str | None,
) -> None:
    try:
        if should_run_hybrid_data_point_review():
            await capture_hybrid_conversation_data_points(
                messages,
                user_id=user_id,
                conversation_id=conversation_id,
                model=model,
            )
            return
        facts = await extract_deep_profile_facts(
            messages,  # type: ignore[arg-type]
            user_id,
            conversation_id=conversation_id,
            model=model,
        )
        for fact in facts:
            upsert_profile_fact(normalize_data_point(fact))
    except Exception:
        logger.exception("agent.deep_facts.capture_failed conversation_id=%s", conversation_id)
