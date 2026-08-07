from __future__ import annotations

import logging
from typing import Any

from agent.memory_engine.data_points import normalize_data_point
from storage import save_data_point_extraction_debug, upsert_profile_fact

logger = logging.getLogger(__name__)


TYPE_STORAGE_POLICY: dict[str, dict[str, Any]] = {
    "profile_fact": {
        "fact_type": "profile_fact",
        "confidence_state": "active",
        "used_for_matching": True,
        "used_for_chat_context": True,
    },
    "matching_fact": {
        "fact_type": "matching_fact",
        "confidence_state": "active",
        "used_for_matching": True,
        "used_for_chat_context": True,
    },
    "chat_learning": {
        "fact_type": "chat_context_fact",
        "confidence_state": "candidate",
        "used_for_matching": False,
        "used_for_chat_context": True,
    },
    "temporary_context": {
        "fact_type": "chat_context_fact",
        "confidence_state": "candidate",
        "used_for_matching": False,
        "used_for_chat_context": True,
    },
    "needs_confirmation": {
        "fact_type": "matching_fact",
        "confidence_state": "candidate",
        "used_for_matching": False,
        "used_for_chat_context": False,
    },
}


def capture_turn_output_data_points(
    *,
    conversation_id: str,
    user_id: str | None,
    user_text: str,
    message_index: int,
    data_points: list[dict[str, Any]],
) -> dict[str, Any]:
    if not user_id or not data_points:
        return {"candidate_count": len(data_points), "saved_count": 0, "skipped_count": len(data_points)}

    saved_count = 0
    skipped_count = 0
    for point in data_points:
        point_type = str(point.get("type") or "").strip().lower()
        if point_type == "do_not_store":
            skipped_count += 1
            _save_debug(
                user_id=user_id,
                conversation_id=conversation_id,
                point=point,
                decision="skip_do_not_store",
                message_index=message_index,
                user_text=user_text,
            )
            continue
        policy = TYPE_STORAGE_POLICY.get(point_type)
        if not policy:
            skipped_count += 1
            continue

        try:
            payload = normalize_data_point(
                {
                    "user_id": user_id,
                    "category": point["category"],
                    "key": point["key"],
                    "label": point["label"],
                    "value": _value_with_data_point_type(point.get("value"), point["label"], point_type),
                    "confidence": point.get("confidence", 0.5),
                    "fact_type": policy["fact_type"],
                    "confidence_state": policy["confidence_state"],
                    "source_kind": "agent_turn_output_v2",
                    "source_id": conversation_id,
                    "evidence": [
                        {
                            "conversation_id": conversation_id,
                            "message_index": message_index,
                            "text": point["evidence"],
                        }
                    ],
                    "status": "active",
                    "visibility": "internal",
                    "used_for_matching": policy["used_for_matching"],
                    "used_for_chat_context": policy["used_for_chat_context"],
                }
            )
            upsert_profile_fact(payload)
            saved_count += 1
            _save_debug(
                user_id=user_id,
                conversation_id=conversation_id,
                point=point,
                decision="saved",
                message_index=message_index,
                user_text=user_text,
            )
        except Exception:
            skipped_count += 1
            logger.exception("agent.turn_output_v2.data_point_save_failed conversation_id=%s", conversation_id)

    return {
        "candidate_count": len(data_points),
        "saved_count": saved_count,
        "skipped_count": skipped_count,
    }


def _value_with_data_point_type(value: Any, label: str, point_type: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return {**value, "_data_point_type": point_type}
    return {"detail": str(value or label), "_data_point_type": point_type}


def _save_debug(
    *,
    user_id: str,
    conversation_id: str,
    point: dict[str, Any],
    decision: str,
    message_index: int,
    user_text: str,
) -> None:
    try:
        save_data_point_extraction_debug(
            {
                "user_id": user_id,
                "source_kind": "agent_turn_output_v2",
                "source_id": conversation_id,
                "candidate_key": point.get("key"),
                "decision": decision,
                "candidate": point,
                "review": {"decision": decision},
                "metadata": {
                    "message_index": message_index,
                    "user_text": user_text[:320],
                },
            }
        )
    except Exception:
        logger.exception("agent.turn_output_v2.debug_save_failed conversation_id=%s", conversation_id)
