from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

from security.encryption import decrypt_json, maybe_encrypt_json

from .database import ENGINE
from .schema import (
    agent_context_snapshots,
    agent_eval_case_results,
    agent_eval_runs,
    agent_message_feedback,
    agent_trace_steps,
    agent_traces,
    agent_usage_events,
)
from .utils import _conversation_user_id, _isoformat_utc

def save_agent_message_feedback(feedback: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": feedback.get("id") or str(uuid4()),
        "user_id": feedback.get("user_id"),
        "conversation_id": feedback["conversation_id"],
        "message_index": feedback["message_index"],
        "rating": feedback["rating"],
        "reason": feedback.get("reason"),
        "comment": feedback.get("comment"),
        "metadata_json": feedback.get("metadata") or {},
    }
    with ENGINE.begin() as connection:
        connection.execute(agent_message_feedback.insert().values(**payload))
        row = connection.execute(
            select(agent_message_feedback).where(agent_message_feedback.c.id == payload["id"])
        ).mappings().first()
    return _agent_message_feedback_from_row(row)


def list_agent_message_feedback(
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    statement = select(agent_message_feedback).order_by(agent_message_feedback.c.created_at.desc())
    if conversation_id:
        statement = statement.where(agent_message_feedback.c.conversation_id == conversation_id)
    if user_id is not None:
        statement = statement.where(agent_message_feedback.c.user_id == user_id)

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_agent_message_feedback_from_row(row) for row in rows]


def _agent_message_feedback_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "message_index": row["message_index"],
        "rating": row["rating"],
        "reason": row["reason"],
        "comment": row["comment"],
        "metadata": row["metadata_json"],
        "created_at": _isoformat_utc(row["created_at"]),
    }


def save_agent_usage_event(event: dict[str, Any]) -> None:
    user_id = event.get("user_id") or _conversation_user_id(event.get("conversation_id"))
    payload = {
        "id": event.get("id") or str(uuid4()),
        "user_id": user_id,
        "conversation_id": event.get("conversation_id"),
        "request_kind": event["request_kind"],
        "provider": event["provider"],
        "model": event.get("model"),
        "success": event["success"],
        "prompt_tokens": event.get("prompt_tokens"),
        "completion_tokens": event.get("completion_tokens"),
        "total_tokens": event.get("total_tokens"),
        "latency_ms": event.get("latency_ms"),
        "estimated_cost_usd": event.get("estimated_cost_usd"),
        "error": event.get("error"),
        "raw_usage_json": event.get("raw_usage") or {},
    }
    if event.get("created_at") is not None:
        payload["created_at"] = event["created_at"]
    with ENGINE.begin() as connection:
        connection.execute(agent_usage_events.insert().values(**payload))


def save_agent_trace(trace: dict[str, Any]) -> dict[str, Any]:
    user_id = trace.get("user_id") or _conversation_user_id(trace.get("conversation_id"))
    payload = {
        "id": trace.get("id") or str(uuid4()),
        "user_id": user_id,
        "conversation_id": trace["conversation_id"],
        "turn_index": trace["turn_index"],
        "agent_mode": trace.get("agent_mode"),
        "agent_tone": trace.get("agent_tone"),
        "model": trace.get("model"),
        "status": trace.get("status") or "running",
        "summary_json": maybe_encrypt_json(user_id, trace.get("summary") or {}),
    }
    with ENGINE.begin() as connection:
        connection.execute(agent_traces.insert().values(**payload))
        row = connection.execute(
            select(agent_traces).where(agent_traces.c.id == payload["id"])
        ).mappings().first()
    return _agent_trace_from_row(row)


def finish_agent_trace(
    trace_id: str,
    *,
    status: str,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    with ENGINE.begin() as connection:
        existing = connection.execute(
            select(agent_traces).where(agent_traces.c.id == trace_id)
        ).mappings().first()
        if not existing:
            return None
        user_id = existing["user_id"]
        existing_summary = decrypt_json(user_id, existing["summary_json"])
        merged_summary = {
            **(existing_summary if isinstance(existing_summary, dict) else {}),
            **(summary or {}),
        }
        connection.execute(
            agent_traces.update()
            .where(agent_traces.c.id == trace_id)
            .values(
                status=status,
                summary_json=maybe_encrypt_json(user_id, merged_summary),
                completed_at=func.now(),
            )
        )
        row = connection.execute(
            select(agent_traces).where(agent_traces.c.id == trace_id)
        ).mappings().first()
    return _agent_trace_from_row(row) if row else None


def save_agent_trace_step(step: dict[str, Any]) -> dict[str, Any]:
    user_id = step.get("user_id") or _conversation_user_id(step.get("conversation_id"))
    payload = {
        "id": step.get("id") or str(uuid4()),
        "trace_id": step["trace_id"],
        "user_id": user_id,
        "conversation_id": step["conversation_id"],
        "step_index": step["step_index"],
        "step_name": step["step_name"],
        "status": step.get("status") or "ok",
        "metadata_json": maybe_encrypt_json(user_id, step.get("metadata") or {}),
    }
    with ENGINE.begin() as connection:
        connection.execute(agent_trace_steps.insert().values(**payload))
        row = connection.execute(
            select(agent_trace_steps).where(agent_trace_steps.c.id == payload["id"])
        ).mappings().first()
    return _agent_trace_step_from_row(row)


def list_agent_traces(
    conversation_id: str | None = None,
    user_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    statement = select(agent_traces).order_by(agent_traces.c.created_at.desc())
    if conversation_id:
        statement = statement.where(agent_traces.c.conversation_id == conversation_id)
    if user_id is not None:
        statement = statement.where(agent_traces.c.user_id == user_id)
    if limit:
        statement = statement.limit(limit)

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_agent_trace_from_row(row) for row in rows]


def list_agent_trace_steps(
    trace_id: str | None = None,
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    statement = select(agent_trace_steps).order_by(
        agent_trace_steps.c.step_index.asc(),
        agent_trace_steps.c.created_at.asc(),
    )
    if trace_id:
        statement = statement.where(agent_trace_steps.c.trace_id == trace_id)
    if conversation_id:
        statement = statement.where(agent_trace_steps.c.conversation_id == conversation_id)
    if user_id is not None:
        statement = statement.where(agent_trace_steps.c.user_id == user_id)

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_agent_trace_step_from_row(row) for row in rows]


def save_agent_eval_run(run: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": run.get("id") or str(uuid4()),
        "suite_name": run["suite_name"],
        "provider": run.get("provider") or "unknown",
        "model": run.get("model"),
        "status": run.get("status") or "running",
        "passed": int(run.get("passed") or 0),
        "failed": int(run.get("failed") or 0),
        "total": int(run.get("total") or 0),
        "metadata_json": run.get("metadata") or {},
    }
    with ENGINE.begin() as connection:
        connection.execute(agent_eval_runs.insert().values(**payload))
        row = connection.execute(
            select(agent_eval_runs).where(agent_eval_runs.c.id == payload["id"])
        ).mappings().first()
    return _agent_eval_run_from_row(row)


def finish_agent_eval_run(
    run_id: str,
    *,
    status: str,
    passed: int,
    failed: int,
    total: int,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    with ENGINE.begin() as connection:
        existing = connection.execute(
            select(agent_eval_runs).where(agent_eval_runs.c.id == run_id)
        ).mappings().first()
        if not existing:
            return None
        existing_metadata = existing["metadata_json"] or {}
        connection.execute(
            agent_eval_runs.update()
            .where(agent_eval_runs.c.id == run_id)
            .values(
                status=status,
                passed=passed,
                failed=failed,
                total=total,
                metadata_json={**existing_metadata, **(metadata or {})},
                completed_at=func.now(),
            )
        )
        row = connection.execute(
            select(agent_eval_runs).where(agent_eval_runs.c.id == run_id)
        ).mappings().first()
    return _agent_eval_run_from_row(row) if row else None


def save_agent_eval_case_result(result: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": result.get("id") or str(uuid4()),
        "run_id": result["run_id"],
        "case_id": result["case_id"],
        "status": result.get("status") or ("passed" if result.get("passed") else "failed"),
        "failures_json": result.get("failures") or [],
        "expected_json": result.get("expected") or {},
        "observed_json": result.get("observed") or {},
        "trace_count": int(result.get("trace_count") or 0),
    }
    with ENGINE.begin() as connection:
        connection.execute(agent_eval_case_results.insert().values(**payload))
        row = connection.execute(
            select(agent_eval_case_results).where(
                agent_eval_case_results.c.id == payload["id"]
            )
        ).mappings().first()
    return _agent_eval_case_result_from_row(row)


def list_agent_eval_runs(limit: int | None = None) -> list[dict[str, Any]]:
    statement = select(agent_eval_runs).order_by(agent_eval_runs.c.created_at.desc())
    if limit:
        statement = statement.limit(limit)
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_agent_eval_run_from_row(row) for row in rows]


def list_agent_eval_case_results(run_id: str | None = None) -> list[dict[str, Any]]:
    statement = select(agent_eval_case_results).order_by(
        agent_eval_case_results.c.created_at.asc()
    )
    if run_id:
        statement = statement.where(agent_eval_case_results.c.run_id == run_id)
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_agent_eval_case_result_from_row(row) for row in rows]


def _agent_eval_run_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "suite_name": row["suite_name"],
        "provider": row["provider"],
        "model": row["model"],
        "status": row["status"],
        "passed": row["passed"],
        "failed": row["failed"],
        "total": row["total"],
        "metadata": row["metadata_json"],
        "created_at": _isoformat_utc(row["created_at"]),
        "completed_at": _isoformat_utc(row["completed_at"]) if row["completed_at"] else None,
    }


def _agent_eval_case_result_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "case_id": row["case_id"],
        "status": row["status"],
        "failures": row["failures_json"],
        "expected": row["expected_json"],
        "observed": row["observed_json"],
        "trace_count": row["trace_count"],
        "created_at": _isoformat_utc(row["created_at"]),
    }


def _agent_trace_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "turn_index": row["turn_index"],
        "agent_mode": row["agent_mode"],
        "agent_tone": row["agent_tone"],
        "model": row["model"],
        "status": row["status"],
        "summary": decrypt_json(row["user_id"], row["summary_json"]),
        "created_at": _isoformat_utc(row["created_at"]),
        "completed_at": _isoformat_utc(row["completed_at"]) if row["completed_at"] else None,
    }


def _agent_trace_step_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "trace_id": row["trace_id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "step_index": row["step_index"],
        "step_name": row["step_name"],
        "status": row["status"],
        "metadata": decrypt_json(row["user_id"], row["metadata_json"]),
        "created_at": _isoformat_utc(row["created_at"]),
    }


def save_agent_context_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    user_id = snapshot.get("user_id") or _conversation_user_id(snapshot.get("conversation_id"))
    payload = {
        "id": snapshot.get("id") or str(uuid4()),
        "user_id": user_id,
        "conversation_id": snapshot["conversation_id"],
        "message_index": snapshot["message_index"],
        "summary_json": maybe_encrypt_json(user_id, snapshot.get("summary") or {}),
        "context_json": maybe_encrypt_json(user_id, snapshot.get("context") or {}),
    }
    with ENGINE.begin() as connection:
        connection.execute(agent_context_snapshots.insert().values(**payload))
        row = connection.execute(
            select(agent_context_snapshots).where(agent_context_snapshots.c.id == payload["id"])
        ).mappings().first()
    return _agent_context_snapshot_from_row(row)


def list_agent_context_snapshots(
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    statement = select(agent_context_snapshots).order_by(
        agent_context_snapshots.c.created_at.desc()
    )
    if conversation_id:
        statement = statement.where(agent_context_snapshots.c.conversation_id == conversation_id)
    if user_id is not None:
        statement = statement.where(agent_context_snapshots.c.user_id == user_id)

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_agent_context_snapshot_from_row(row) for row in rows]


def _agent_context_snapshot_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "message_index": row["message_index"],
        "summary": decrypt_json(row["user_id"], row["summary_json"]),
        "context": decrypt_json(row["user_id"], row["context_json"]),
        "created_at": _isoformat_utc(row["created_at"]),
    }


def list_agent_usage_events(
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    statement = select(agent_usage_events).order_by(agent_usage_events.c.created_at.desc())
    if conversation_id:
        statement = statement.where(agent_usage_events.c.conversation_id == conversation_id)
    if user_id is not None:
        statement = statement.where(agent_usage_events.c.user_id == user_id)

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()

    return [
        {
            "id": row["id"],
            "user_id": row["user_id"],
            "conversation_id": row["conversation_id"],
            "request_kind": row["request_kind"],
            "provider": row["provider"],
            "model": row["model"],
            "success": row["success"],
            "prompt_tokens": row["prompt_tokens"],
            "completion_tokens": row["completion_tokens"],
            "total_tokens": row["total_tokens"],
            "latency_ms": row["latency_ms"],
            "estimated_cost_usd": row["estimated_cost_usd"],
            "error": row["error"],
            "raw_usage": row["raw_usage_json"],
            "created_at": _isoformat_utc(row["created_at"]),
        }
        for row in rows
    ]


def summarize_agent_usage(
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    events = list_agent_usage_events(conversation_id, user_id)
    successful_events = [event for event in events if event["success"]]
    successful_chat_events = [
        event for event in successful_events if event["request_kind"] == "chat_reply"
    ]
    chat_message_count = len(successful_chat_events)
    chat_prompt_tokens = sum(event["prompt_tokens"] or 0 for event in successful_chat_events)
    chat_completion_tokens = sum(
        event["completion_tokens"] or 0 for event in successful_chat_events
    )
    chat_total_tokens = sum(event["total_tokens"] or 0 for event in successful_chat_events)
    estimated_cost_usd = round(
        sum(event["estimated_cost_usd"] or 0 for event in events),
        8,
    )
    provider_model_breakdown = _provider_model_usage_breakdown(events)
    latest_event = events[0] if events else None
    return {
        "conversation_id": conversation_id,
        "request_count": len(events),
        "successful_request_count": len(successful_events),
        "failed_request_count": len(events) - len(successful_events),
        "prompt_tokens": sum(event["prompt_tokens"] or 0 for event in events),
        "completion_tokens": sum(event["completion_tokens"] or 0 for event in events),
        "total_tokens": sum(event["total_tokens"] or 0 for event in events),
        "chat_message_count": chat_message_count,
        "average_tokens_per_message": _average_int(chat_total_tokens, chat_message_count),
        "average_prompt_tokens_per_message": _average_int(chat_prompt_tokens, chat_message_count),
        "average_completion_tokens_per_message": _average_int(
            chat_completion_tokens,
            chat_message_count,
        ),
        "estimated_cost_usd": estimated_cost_usd,
        "estimated_cost_inr": _estimated_cost_inr(estimated_cost_usd),
        "latest_provider": latest_event["provider"] if latest_event else None,
        "latest_model": latest_event["model"] if latest_event else None,
        "provider_model_breakdown": provider_model_breakdown,
    }


def _provider_model_usage_breakdown(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    breakdown: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        provider = str(event.get("provider") or "unknown")
        model = str(event.get("model") or "unknown")
        key = (provider, model)
        if key not in breakdown:
            breakdown[key] = {
                "provider": provider,
                "model": model,
                "request_count": 0,
                "successful_request_count": 0,
                "failed_request_count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0,
                "latest_at": None,
            }
        row = breakdown[key]
        row["request_count"] += 1
        if event.get("success"):
            row["successful_request_count"] += 1
        else:
            row["failed_request_count"] += 1
        row["prompt_tokens"] += event.get("prompt_tokens") or 0
        row["completion_tokens"] += event.get("completion_tokens") or 0
        row["total_tokens"] += event.get("total_tokens") or 0
        row["estimated_cost_usd"] = round(
            row["estimated_cost_usd"] + (event.get("estimated_cost_usd") or 0),
            8,
        )
        created_at = event.get("created_at")
        if created_at and (row["latest_at"] is None or str(created_at) > str(row["latest_at"])):
            row["latest_at"] = created_at

    return sorted(
        breakdown.values(),
        key=lambda row: (int(row["total_tokens"]), int(row["request_count"])),
        reverse=True,
    )


def _average_int(total: int, count: int) -> int:
    if count <= 0:
        return 0
    return round(total / count)


def _estimated_cost_inr(estimated_cost_usd: float) -> float | None:
    usd_to_inr = float(os.getenv("USD_TO_INR", "0") or 0)
    if usd_to_inr == 0:
        return None
    return round(estimated_cost_usd * usd_to_inr, 6)
