from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

from security.encryption import decrypt_json, maybe_encrypt_json

from .database import ENGINE
from .schema import data_point_extraction_debug, data_point_feedback, profile_facts
from .utils import _isoformat_utc

def upsert_profile_fact(fact: dict[str, Any]) -> dict[str, Any]:
    payload = _profile_fact_payload(fact)
    with ENGINE.begin() as connection:
        existing = connection.execute(
            select(profile_facts).where(
                profile_facts.c.user_id == payload["user_id"],
                profile_facts.c.category == payload["category"],
                profile_facts.c.key == payload["key"],
            )
        ).mappings().first()
        if existing:
            merged = _merge_profile_fact(existing, payload)
            connection.execute(
                profile_facts.update()
                .where(profile_facts.c.id == existing["id"])
                .values(**merged, updated_at=func.now())
            )
            fact_id = existing["id"]
        else:
            fact_id = payload["id"]
            connection.execute(profile_facts.insert().values(**payload))

        row = connection.execute(
            select(profile_facts).where(profile_facts.c.id == fact_id)
        ).mappings().first()
    return _profile_fact_from_row(row)


def list_profile_facts(
    user_id: str,
    statuses: set[str] | None = None,
    used_for_matching: bool | None = None,
    used_for_chat_context: bool | None = None,
) -> list[dict[str, Any]]:
    statement = (
        select(profile_facts)
        .where(profile_facts.c.user_id == user_id)
        .order_by(
            profile_facts.c.category.asc(),
            profile_facts.c.confidence.desc(),
            profile_facts.c.updated_at.desc(),
        )
    )
    if statuses:
        statement = statement.where(profile_facts.c.status.in_(statuses))
    if used_for_matching is not None:
        statement = statement.where(profile_facts.c.used_for_matching == used_for_matching)
    if used_for_chat_context is not None:
        statement = statement.where(profile_facts.c.used_for_chat_context == used_for_chat_context)

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return _dedupe_profile_fact_dicts([_profile_fact_from_row(row) for row in rows])


def delete_profile_facts_by_source(
    source_kind: str,
    source_ids: list[str],
    user_id: str | None = None,
) -> int:
    if not source_ids:
        return 0
    select_statement = select(profile_facts.c.id).where(
        profile_facts.c.source_kind == source_kind,
        profile_facts.c.source_id.in_(source_ids),
    )
    if user_id is not None:
        select_statement = select_statement.where(profile_facts.c.user_id == user_id)
    statement = profile_facts.delete().where(
        profile_facts.c.source_kind == source_kind,
        profile_facts.c.source_id.in_(source_ids),
    )
    if user_id is not None:
        statement = statement.where(profile_facts.c.user_id == user_id)
    with ENGINE.begin() as connection:
        fact_ids = [row[0] for row in connection.execute(select_statement).all()]
        if fact_ids:
            connection.execute(
                data_point_feedback.delete().where(
                    data_point_feedback.c.profile_fact_id.in_(fact_ids)
                )
            )
        result = connection.execute(statement)
    return int(result.rowcount or 0)


def get_profile_fact(fact_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    statement = select(profile_facts).where(profile_facts.c.id == fact_id)
    if user_id is not None:
        statement = statement.where(profile_facts.c.user_id == user_id)

    with ENGINE.begin() as connection:
        row = connection.execute(statement).mappings().first()
    return _profile_fact_from_row(row) if row else None


def save_data_point_feedback(feedback: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": feedback.get("id") or str(uuid4()),
        "user_id": feedback["user_id"],
        "profile_fact_id": feedback["profile_fact_id"],
        "rating": feedback["rating"],
        "reason": feedback.get("reason"),
        "comment": feedback.get("comment"),
        "metadata_json": feedback.get("metadata") or {},
    }
    with ENGINE.begin() as connection:
        fact_row = connection.execute(
            select(profile_facts).where(
                profile_facts.c.id == payload["profile_fact_id"],
                profile_facts.c.user_id == payload["user_id"],
            )
        ).mappings().first()
        existing = connection.execute(
            select(data_point_feedback).where(
                data_point_feedback.c.user_id == payload["user_id"],
                data_point_feedback.c.profile_fact_id == payload["profile_fact_id"],
            )
        ).mappings().first()
        metadata_json = _data_point_feedback_metadata(
            payload["metadata_json"],
            existing,
            fact_row,
        )
        payload["metadata_json"] = metadata_json
        if existing:
            feedback_id = existing["id"]
            connection.execute(
                data_point_feedback.update()
                .where(data_point_feedback.c.id == feedback_id)
                .values(
                    rating=payload["rating"],
                    reason=payload["reason"],
                    comment=payload["comment"],
                    metadata_json=payload["metadata_json"],
                    updated_at=func.now(),
                )
            )
        else:
            feedback_id = payload["id"]
            connection.execute(data_point_feedback.insert().values(**payload))

        if fact_row:
            connection.execute(
                profile_facts.update()
                .where(profile_facts.c.id == payload["profile_fact_id"])
                .values(
                    **_profile_fact_feedback_update_values(
                        payload["rating"],
                        metadata_json,
                        fact_row,
                    ),
                    updated_at=func.now(),
                )
            )

        row = connection.execute(
            select(data_point_feedback).where(data_point_feedback.c.id == feedback_id)
        ).mappings().first()
    return _data_point_feedback_from_row(row)


def list_data_point_feedback(
    user_id: str | None = None,
    profile_fact_id: str | None = None,
) -> list[dict[str, Any]]:
    statement = select(data_point_feedback).order_by(data_point_feedback.c.updated_at.desc())
    if user_id is not None:
        statement = statement.where(data_point_feedback.c.user_id == user_id)
    if profile_fact_id is not None:
        statement = statement.where(data_point_feedback.c.profile_fact_id == profile_fact_id)

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_data_point_feedback_from_row(row) for row in rows]


def save_data_point_extraction_debug(entry: dict[str, Any]) -> dict[str, Any]:
    user_id = entry.get("user_id")
    payload = {
        "id": entry.get("id") or str(uuid4()),
        "user_id": user_id,
        "source_kind": entry.get("source_kind") or "unknown",
        "source_id": entry.get("source_id"),
        "import_id": entry.get("import_id"),
        "candidate_key": entry.get("candidate_key"),
        "decision": str(entry.get("decision") or "unknown"),
        "candidate_json": maybe_encrypt_json(user_id, entry.get("candidate") or {}),
        "review_json": maybe_encrypt_json(user_id, entry.get("review") or {}),
        "metadata_json": maybe_encrypt_json(user_id, entry.get("metadata") or {}),
    }
    with ENGINE.begin() as connection:
        connection.execute(data_point_extraction_debug.insert().values(**payload))
        row = connection.execute(
            select(data_point_extraction_debug).where(
                data_point_extraction_debug.c.id == payload["id"]
            )
        ).mappings().first()
    return _data_point_extraction_debug_from_row(row)


def list_data_point_extraction_debug(
    user_id: str | None = None,
    source_id: str | None = None,
    import_id: str | None = None,
    decision: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    statement = select(data_point_extraction_debug).order_by(
        data_point_extraction_debug.c.created_at.desc()
    )
    if user_id is not None:
        statement = statement.where(data_point_extraction_debug.c.user_id == user_id)
    if source_id is not None:
        statement = statement.where(data_point_extraction_debug.c.source_id == source_id)
    if import_id is not None:
        statement = statement.where(data_point_extraction_debug.c.import_id == import_id)
    if decision is not None:
        statement = statement.where(data_point_extraction_debug.c.decision == decision)
    if limit is not None:
        statement = statement.limit(limit)

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_data_point_extraction_debug_from_row(row) for row in rows]


def _profile_fact_payload(fact: dict[str, Any]) -> dict[str, Any]:
    category, key = _canonical_profile_fact_category_key(
        fact["category"],
        fact["key"],
        fact.get("label"),
        fact.get("value") or fact.get("value_json"),
    )
    return {
        "id": fact.get("id") or str(uuid4()),
        "user_id": fact["user_id"],
        "category": category,
        "key": key,
        "value_json": fact.get("value") or fact.get("value_json") or {},
        "label": fact["label"],
        "confidence": _bounded_confidence(fact.get("confidence", 0.5)),
        "source_kind": fact.get("source_kind") or "agent_chat",
        "source_id": fact.get("source_id"),
        "evidence_json": _normalize_evidence_items(
            fact.get("evidence") or fact.get("evidence_json") or []
        ),
        "status": fact.get("status") or "active",
        "visibility": fact.get("visibility") or "internal",
        "used_for_matching": bool(fact.get("used_for_matching", True)),
        "used_for_chat_context": bool(fact.get("used_for_chat_context", False)),
    }


def _canonical_profile_fact_category_key(
    category: Any,
    key: Any,
    label: Any,
    value: Any,
) -> tuple[str, str]:
    raw_category = str(category or "")
    raw_key = str(key or "")
    terms = _fact_term_set(" ".join([raw_category, raw_key, str(label or ""), _fact_value_text(value)]))
    if terms & {"honesty", "honest", "truthful", "transparent", "transparency"}:
        return "values", "honesty"
    if terms & {"respect", "respectful"}:
        return "values", "mutual_respect"
    if "family" in terms:
        return "values", "family"
    if terms & {"ambition", "ambitious", "career", "growth"}:
        return "values", "ambition"
    if terms & {"maturity", "mature"} and "emotional" in terms:
        return "values", "emotional_maturity"
    if "calm" in terms or {"low", "drama"}.issubset(terms):
        return "communication", "calm_low_drama"
    return raw_category, raw_key


def _merge_profile_fact(existing: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    evidence = _dedupe_evidence(
        list(existing["evidence_json"] or []) + list(incoming["evidence_json"] or [])
    )
    if existing["status"] == "rejected":
        return {
            "value_json": incoming["value_json"],
            "label": incoming["label"],
            "confidence": min(existing["confidence"] or 0, incoming["confidence"], 0.2),
            "source_kind": incoming["source_kind"],
            "source_id": incoming["source_id"] or existing["source_id"],
            "evidence_json": evidence,
            "status": "rejected",
            "visibility": incoming["visibility"] or existing["visibility"],
            "used_for_matching": False,
            "used_for_chat_context": False,
        }
    return {
        "value_json": incoming["value_json"],
        "label": incoming["label"],
        "confidence": max(existing["confidence"] or 0, incoming["confidence"]),
        "source_kind": incoming["source_kind"],
        "source_id": incoming["source_id"] or existing["source_id"],
        "evidence_json": evidence,
        "status": incoming["status"] or existing["status"],
        "visibility": incoming["visibility"] or existing["visibility"],
        "used_for_matching": incoming["used_for_matching"],
        "used_for_chat_context": incoming["used_for_chat_context"],
    }


def _data_point_feedback_metadata(
    metadata: Any,
    existing_feedback: Any | None,
    fact_row: Any | None,
) -> dict[str, Any]:
    payload = dict(metadata) if isinstance(metadata, dict) else {}
    existing_metadata = (
        existing_feedback["metadata_json"]
        if existing_feedback and isinstance(existing_feedback["metadata_json"], dict)
        else {}
    )
    if isinstance(existing_metadata.get("original_fact"), dict):
        payload["original_fact"] = existing_metadata["original_fact"]
    elif fact_row:
        payload["original_fact"] = {
            "status": fact_row["status"],
            "confidence": fact_row["confidence"],
            "used_for_matching": fact_row["used_for_matching"],
            "used_for_chat_context": fact_row["used_for_chat_context"],
        }
    return payload


def _profile_fact_feedback_update_values(
    rating: str,
    metadata: dict[str, Any],
    fact_row: Any,
) -> dict[str, Any]:
    current_confidence = _bounded_confidence(fact_row["confidence"])
    if rating == "disagree":
        return {
            "status": "rejected",
            "confidence": min(current_confidence, 0.2),
            "used_for_matching": False,
            "used_for_chat_context": False,
        }

    original = metadata.get("original_fact") if isinstance(metadata.get("original_fact"), dict) else {}
    original_confidence = _bounded_confidence(original.get("confidence", current_confidence))
    return {
        "status": "active",
        "confidence": min(1.0, max(current_confidence, original_confidence, 0.9)),
        "used_for_matching": bool(original.get("used_for_matching", fact_row["used_for_matching"])),
        "used_for_chat_context": bool(
            original.get("used_for_chat_context", fact_row["used_for_chat_context"])
        ),
    }


def _dedupe_evidence(evidence_items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    deduped: list[Any] = []
    for item in _normalize_evidence_items(evidence_items):
        key = repr(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _normalize_evidence_items(evidence_items: list[Any]) -> list[Any]:
    normalized_items = []
    for item in evidence_items:
        if not isinstance(item, dict):
            normalized_items.append(item)
            continue
        normalized = dict(item)
        text = str(normalized.get("text") or normalized.get("quote") or "").strip()
        if text:
            normalized["text"] = text
            normalized["quote"] = text
        normalized_items.append(normalized)
    return normalized_items


def _dedupe_profile_fact_dicts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for fact in facts:
        identity = _profile_fact_identity(fact)
        existing = deduped.get(identity)
        if not existing:
            deduped[identity] = fact
            continue
        deduped[identity] = _merge_profile_fact_dict(existing, fact)
    return list(deduped.values())


def _merge_profile_fact_dict(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    if float(incoming.get("confidence") or 0) > float(existing.get("confidence") or 0):
        base = {**existing, **incoming}
    else:
        base = dict(existing)
    base["confidence"] = max(
        float(existing.get("confidence") or 0),
        float(incoming.get("confidence") or 0),
    )
    base["evidence"] = _dedupe_evidence(
        list(existing.get("evidence") or []) + list(incoming.get("evidence") or [])
    )
    return base


def _profile_fact_identity(fact: dict[str, Any]) -> tuple[str, str]:
    user_id = str(fact.get("user_id") or "")
    category = _normalized_fact_terms(str(fact.get("category") or ""))
    label_terms = _normalized_fact_terms(str(fact.get("label") or ""))
    value_terms = _normalized_fact_terms(_fact_value_text(fact.get("value")))
    key_terms = _normalized_fact_terms(str(fact.get("key") or ""))
    meaning = label_terms or value_terms or key_terms
    return user_id, f"{category}:{meaning}"


def _fact_value_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(str(part) for part in value.values())
    if isinstance(value, list):
        return " ".join(str(part) for part in value)
    return str(value or "")


def _normalized_fact_terms(text_value: str) -> str:
    return "_".join(sorted(_fact_term_set(text_value)))


def _fact_term_set(text_value: str) -> set[str]:
    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "be",
        "for",
        "has",
        "is",
        "of",
        "the",
        "to",
        "use",
        "uses",
        "using",
        "with",
    }
    words = [
        _singularize_token(token)
        for token in "".join(
            character.lower() if character.isalnum() else " " for character in text_value
        ).split()
        if token not in stopwords
    ]
    return set(words)


def _singularize_token(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _bounded_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.5
    return max(0.0, min(1.0, confidence))


def _profile_fact_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "category": row["category"],
        "key": row["key"],
        "value": row["value_json"],
        "label": row["label"],
        "confidence": row["confidence"],
        "source_kind": row["source_kind"],
        "source_id": row["source_id"],
        "evidence": row["evidence_json"],
        "status": row["status"],
        "visibility": row["visibility"],
        "used_for_matching": row["used_for_matching"],
        "used_for_chat_context": row["used_for_chat_context"],
        "created_at": _isoformat_utc(row["created_at"]),
        "updated_at": _isoformat_utc(row["updated_at"]),
    }


def _data_point_feedback_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "profile_fact_id": row["profile_fact_id"],
        "rating": row["rating"],
        "reason": row["reason"],
        "comment": row["comment"],
        "metadata": row["metadata_json"],
        "created_at": _isoformat_utc(row["created_at"]),
        "updated_at": _isoformat_utc(row["updated_at"]),
    }


def _data_point_extraction_debug_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "source_kind": row["source_kind"],
        "source_id": row["source_id"],
        "import_id": row["import_id"],
        "candidate_key": row["candidate_key"],
        "decision": row["decision"],
        "candidate": decrypt_json(row["user_id"], row["candidate_json"]),
        "review": decrypt_json(row["user_id"], row["review_json"]),
        "metadata": decrypt_json(row["user_id"], row["metadata_json"]),
        "created_at": _isoformat_utc(row["created_at"]),
    }

