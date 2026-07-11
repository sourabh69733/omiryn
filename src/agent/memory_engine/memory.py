from __future__ import annotations

import logging
import os

from agent.memory_engine.data_point_extraction import (
    capture_hybrid_conversation_data_points,
    should_run_hybrid_data_point_review,
)
from agent.memory_engine.agent_behavior import extract_agent_behavior_rules_from_message
from agent.memory_engine.data_points import normalize_data_point
from agent.memory_engine.profile_facts import extract_profile_facts_from_message
from agent.memory_engine.utils import conversation_extraction_window
from agent.runtime.providers import extract_deep_profile_facts
from storage import (
    list_data_point_extraction_debug,
    save_data_point_extraction_debug,
    upsert_agent_behavior_rule,
    upsert_profile_fact,
)

logger = logging.getLogger(__name__)
DEEP_FACT_EXTRACTION_INTERVAL = int(os.getenv("PROFILE_FACT_DEEP_EXTRACT_INTERVAL", "7"))


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
    for rule in extract_agent_behavior_rules_from_message(
        user_id=user_id,
        conversation_id=conversation_id,
        message=message,
        message_index=message_index,
    ):
        upsert_agent_behavior_rule(rule)


def should_run_deep_profile_fact_extraction(
    user_id: str | None,
    messages: list[dict[str, object]],
    quality_valid: bool,
) -> bool:
    return should_run_conversation_data_point_extraction(
        conversation_id="",
        user_id=user_id,
        messages=messages,
        quality_valid=quality_valid,
    )


def should_run_conversation_data_point_extraction(
    conversation_id: str,
    user_id: str | None,
    messages: list[dict[str, object]],
    quality_valid: bool,
) -> bool:
    interval = deep_fact_extraction_interval()
    if not user_id or not quality_valid or interval <= 0:
        return False
    pending_messages = pending_data_point_messages(
        conversation_id=conversation_id,
        user_id=user_id,
        messages=messages,
    )
    return len(pending_messages) >= interval


def pending_data_point_messages(
    *,
    conversation_id: str,
    user_id: str,
    messages: list[dict[str, object]],
) -> list[dict[str, object]]:
    last_extracted_index = _last_extracted_message_index(user_id, conversation_id)
    pending: list[dict[str, object]] = []
    for index, message in enumerate(messages):
        if message.get("role") != "user":
            continue
        if message.get("quality") in {"low_information", "simple_acknowledgement"}:
            continue
        if not message.get("content"):
            continue
        if index <= last_extracted_index:
            continue
        pending.append({**message, "message_index": index})
    return pending


def _last_extracted_message_index(user_id: str, conversation_id: str) -> int:
    if not conversation_id:
        return -1
    rows = list_data_point_extraction_debug(
        user_id=user_id,
        source_id=conversation_id,
        limit=50,
    )
    indexes: list[int] = []
    for row in rows:
        if row.get("source_kind") != "agent_conversation":
            continue
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        window = metadata.get("extraction_window") if isinstance(metadata, dict) else None
        if isinstance(window, dict) and isinstance(window.get("end_message_index"), int):
            indexes.append(window["end_message_index"])
    return max(indexes) if indexes else -1


async def capture_deep_profile_facts_from_conversation(
    conversation_id: str,
    user_id: str,
    messages: list[dict[str, object]],
    model: str | None,
) -> None:
    try:
        pending_messages = pending_data_point_messages(
            conversation_id=conversation_id,
            user_id=user_id,
            messages=messages,
        )
        if not pending_messages:
            return
        if should_run_hybrid_data_point_review():
            await capture_hybrid_conversation_data_points(
                pending_messages,
                user_id=user_id,
                conversation_id=conversation_id,
                model=model,
            )
            return
        facts = await extract_deep_profile_facts(
            pending_messages,  # type: ignore[arg-type]
            user_id,
            conversation_id=conversation_id,
            model=model,
        )
        _save_conversation_extraction_marker(
            user_id=user_id,
            conversation_id=conversation_id,
            messages=pending_messages,
            decision="extract" if facts else "no_useful_data",
            fact_count=len(facts),
            extractor="deep_profile_fact_extract",
        )
        for fact in facts:
            upsert_profile_fact(normalize_data_point(fact))
    except Exception:
        logger.exception("agent.deep_facts.capture_failed conversation_id=%s", conversation_id)


def _save_conversation_extraction_marker(
    *,
    user_id: str,
    conversation_id: str,
    messages: list[dict[str, object]],
    decision: str,
    fact_count: int,
    extractor: str,
) -> None:
    window = conversation_extraction_window(messages)
    if not window:
        return
    save_data_point_extraction_debug(
        {
            "user_id": user_id,
            "source_kind": "agent_conversation",
            "source_id": conversation_id,
            "import_id": None,
            "candidate_key": "conversation_window",
            "decision": decision,
            "candidate": {
                "key": "conversation_window",
                "message_count": window["user_message_count"],
            },
            "review": {
                "decision": decision,
                "reason": "Processed pending user-only message window.",
                "fact_count": fact_count,
            },
            "metadata": {
                "title": "In-app conversation",
                "extractor": extractor,
                "extraction_window": window,
            },
        }
    )
