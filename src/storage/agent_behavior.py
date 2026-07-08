from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

from .database import ENGINE
from .schema import agent_behavior_rules
from .utils import _isoformat_utc


def upsert_agent_behavior_rule(rule: dict[str, Any]) -> dict[str, Any]:
    payload = _agent_behavior_rule_payload(rule)
    with ENGINE.begin() as connection:
        existing = connection.execute(
            select(agent_behavior_rules).where(
                agent_behavior_rules.c.user_id == payload["user_id"],
                agent_behavior_rules.c.category == payload["category"],
                agent_behavior_rules.c.key == payload["key"],
            )
        ).mappings().first()
        if existing:
            rule_id = existing["id"]
            connection.execute(
                agent_behavior_rules.update()
                .where(agent_behavior_rules.c.id == rule_id)
                .values(
                    rule_text=payload["rule_text"],
                    avoid_text=payload["avoid_text"],
                    prefer_text=payload["prefer_text"],
                    confidence=max(float(existing["confidence"]), payload["confidence"]),
                    priority=max(int(existing["priority"]), payload["priority"]),
                    source_kind=payload["source_kind"],
                    source_id=payload["source_id"],
                    evidence_json=_merge_evidence(existing["evidence_json"], payload["evidence_json"]),
                    status=payload["status"],
                    updated_at=func.now(),
                )
            )
        else:
            rule_id = payload["id"]
            connection.execute(agent_behavior_rules.insert().values(**payload))

        row = connection.execute(
            select(agent_behavior_rules).where(agent_behavior_rules.c.id == rule_id)
        ).mappings().first()
    return _agent_behavior_rule_from_row(row)


def list_agent_behavior_rules(
    user_id: str | None,
    *,
    status: str = "active",
    limit: int = 12,
) -> list[dict[str, Any]]:
    if not user_id:
        return []
    statement = (
        select(agent_behavior_rules)
        .where(
            agent_behavior_rules.c.user_id == user_id,
            agent_behavior_rules.c.status == status,
        )
        .order_by(
            agent_behavior_rules.c.priority.desc(),
            agent_behavior_rules.c.confidence.desc(),
            agent_behavior_rules.c.updated_at.desc(),
        )
        .limit(limit)
    )
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_agent_behavior_rule_from_row(row) for row in rows]


def _agent_behavior_rule_payload(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": rule.get("id") or str(uuid4()),
        "user_id": rule["user_id"],
        "category": str(rule.get("category") or "agent_behavior"),
        "key": str(rule.get("key") or "general").strip().lower().replace(" ", "_"),
        "rule_text": str(rule["rule_text"]).strip(),
        "avoid_text": rule.get("avoid_text"),
        "prefer_text": rule.get("prefer_text"),
        "confidence": _bounded_confidence(rule.get("confidence", 0.75)),
        "priority": int(rule.get("priority") or 80),
        "source_kind": rule.get("source_kind") or "agent_chat",
        "source_id": rule.get("source_id"),
        "evidence_json": _normalize_evidence(rule.get("evidence") or rule.get("evidence_json") or []),
        "status": rule.get("status") or "active",
    }


def _agent_behavior_rule_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "category": row["category"],
        "key": row["key"],
        "rule_text": row["rule_text"],
        "avoid_text": row["avoid_text"],
        "prefer_text": row["prefer_text"],
        "confidence": float(row["confidence"]),
        "priority": int(row["priority"]),
        "source_kind": row["source_kind"],
        "source_id": row["source_id"],
        "evidence": row["evidence_json"] or [],
        "status": row["status"],
        "created_at": _isoformat_utc(row["created_at"]),
        "updated_at": _isoformat_utc(row["updated_at"]),
    }


def _normalize_evidence(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            normalized.append(
                {
                    "source_kind": item.get("source_kind"),
                    "source_id": item.get("source_id"),
                    "message_index": item.get("message_index"),
                    "quote": str(item.get("quote") or "")[:500],
                }
            )
    return normalized[-5:]


def _merge_evidence(existing: Any, incoming: Any) -> list[dict[str, Any]]:
    return _normalize_evidence([*(existing or []), *(incoming or [])])


def _bounded_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.75
    return max(0.0, min(1.0, confidence))
