from __future__ import annotations

from fastapi import APIRouter, Depends

from security.auth import CurrentUser, require_user
from storage import (
    list_agent_trace_steps,
    list_agent_traces,
    list_agent_usage_events,
    summarize_agent_usage,
)

from ..helpers import _configured_usage_limits, _get_existing_conversation, _user_id

router = APIRouter()


@router.get("/api/agent/usage")
async def agent_usage(
    conversation_id: str | None = None,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    if conversation_id:
        _get_existing_conversation(conversation_id, user)
    owner_id = _user_id(user)
    return {
        "summary": summarize_agent_usage(conversation_id, owner_id),
        "events": list_agent_usage_events(conversation_id, owner_id),
        "limits": _configured_usage_limits(),
    }


@router.get("/api/agent/conversations/{conversation_id}/usage")
async def conversation_agent_usage(
    conversation_id: str,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    _get_existing_conversation(conversation_id, user)
    return {
        "summary": summarize_agent_usage(conversation_id, _user_id(user)),
        "events": list_agent_usage_events(conversation_id, _user_id(user)),
        "limits": _configured_usage_limits(),
    }


@router.get("/api/agent/conversations/{conversation_id}/traces")
async def conversation_agent_traces(
    conversation_id: str,
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    _get_existing_conversation(conversation_id, user)
    traces = list_agent_traces(conversation_id, _user_id(user))
    steps = list_agent_trace_steps(conversation_id=conversation_id, user_id=_user_id(user))
    steps_by_trace: dict[str, list[dict[str, object]]] = {}
    for step in steps:
        steps_by_trace.setdefault(str(step["trace_id"]), []).append(step)
    return {
        "count": len(traces),
        "traces": [
            {
                **trace,
                "steps": steps_by_trace.get(str(trace["id"]), []),
            }
            for trace in traces
        ],
    }
