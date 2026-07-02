from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.context_engine.engine import build_model_context_package
from agent.memory_engine.memory import capture_profile_facts_from_user_message
from agent.runtime.providers import assess_user_message_quality, generate_agent_reply
from storage import (
    finish_agent_trace,
    save_agent_context_snapshot,
    save_agent_trace,
    save_agent_trace_step,
)


@dataclass(frozen=True)
class AgentTurnResult:
    messages: list[dict[str, Any]]
    quality_valid: bool


async def run_agent_turn(
    *,
    conversation_id: str,
    messages: list[dict[str, Any]],
    user_text: str,
    user_id: str | None,
    user_profile: dict[str, Any] | None,
    model: str | None,
    agent_mode: str,
    agent_tone: str,
    style_source_id: str | None,
    agent_name: str | None = None,
) -> AgentTurnResult:
    updated_messages = [dict(message) for message in messages]
    trace = save_agent_trace(
        {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "turn_index": len(messages) + 1,
            "agent_mode": agent_mode,
            "agent_tone": agent_tone,
            "model": model,
            "status": "running",
            "summary": {
                "starting_message_count": len(messages),
                "agent_name_configured": bool(agent_name),
                "style_source_selected": bool(style_source_id),
            },
        }
    )
    trace_id = trace["id"]

    user_message: dict[str, Any] = {"role": "user", "content": user_text}
    quality = assess_user_message_quality(updated_messages + [user_message])
    quality_valid = bool(quality["valid"])
    if not quality_valid:
        user_message["quality"] = "low_information"
    save_agent_trace_step(
        {
            "trace_id": trace_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "step_index": 0,
            "step_name": "input_guardrail",
            "status": "ok" if quality_valid else "blocked",
            "metadata": {
                "quality_valid": quality_valid,
                "message_chars": len(user_text),
                "reply_provided": bool(quality.get("reply")),
            },
        }
    )

    updated_messages.append(user_message)
    capture_profile_facts_from_user_message(
        conversation_id,
        user_id,
        user_text,
        len(updated_messages) - 1,
        quality_valid,
    )
    save_agent_trace_step(
        {
            "trace_id": trace_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "step_index": 1,
            "step_name": "memory_write",
            "status": "ok" if user_id and quality_valid else "skipped",
            "metadata": {
                "user_scoped": bool(user_id),
                "quality_valid": quality_valid,
                "source_kind": "agent_chat",
            },
        }
    )
    context_package = build_model_context_package(
        conversation_id=conversation_id,
        user_text=user_text,
        user_id=user_id,
        user_profile=user_profile,
        model=model,
        agent_tone=agent_tone,
        agent_name=agent_name,
        style_source_id=style_source_id,
        user_message_index=len(updated_messages) - 1,
        assistant_message_index=len(updated_messages),
    )
    save_agent_trace_step(
        {
            "trace_id": trace_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "step_index": 2,
            "step_name": "retrieval",
            "status": "ok",
            "metadata": {
                "source_count": len(context_package.context_sources),
                "source_types": _source_type_counts(context_package.context_sources),
                "has_user_profile": bool(context_package.user_profile),
                "query_intent": list(context_package.query_intent.labels)
                if context_package.query_intent
                else [],
            },
        }
    )
    context_snapshot = context_package.snapshot or {}
    save_agent_trace_step(
        {
            "trace_id": trace_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "step_index": 3,
            "step_name": "context_pack",
            "status": "ok",
            "metadata": context_snapshot.get("summary") or {},
        }
    )
    try:
        reply = await generate_agent_reply(
            updated_messages,
            conversation_id=conversation_id,
            model=model,
            agent_mode=agent_mode,
            agent_tone=agent_tone,
            agent_name=agent_name,
            context_sources=context_package.context_sources,
            user_profile=context_package.user_profile,
            system_prompt=context_package.system_prompt,
        )
    except Exception as error:
        save_agent_trace_step(
            {
                "trace_id": trace_id,
                "user_id": user_id,
                "conversation_id": conversation_id,
                "step_index": 4,
                "step_name": "model_call",
                "status": "failed",
                "metadata": {
                    "error_type": type(error).__name__,
                    "error": str(error)[:240],
                },
            }
        )
        finish_agent_trace(
            trace_id,
            status="failed",
            summary={"error_type": type(error).__name__},
        )
        raise
    save_agent_trace_step(
        {
            "trace_id": trace_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "step_index": 4,
            "step_name": "model_call",
            "status": "ok",
            "metadata": {
                "reply_chars": len(reply),
                "model": model,
                "prompt_version": context_package.prompt_version,
                "agent_mode": agent_mode,
                "agent_tone": agent_tone,
            },
        }
    )
    updated_messages.append({"role": "assistant", "content": reply})
    save_agent_context_snapshot(context_snapshot)
    save_agent_trace_step(
        {
            "trace_id": trace_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "step_index": 5,
            "step_name": "context_snapshot",
            "status": "ok",
            "metadata": {
                "message_index": context_snapshot["message_index"],
                "included_source_count": context_snapshot["summary"].get("included_source_count"),
                "rough_context_tokens": context_snapshot["summary"].get("rough_context_tokens"),
            },
        }
    )
    finish_agent_trace(
        trace_id,
        status="completed",
        summary={
            "ending_message_count": len(updated_messages),
            "quality_valid": quality_valid,
            "reply_chars": len(reply),
        },
    )
    return AgentTurnResult(messages=updated_messages, quality_valid=quality_valid)


def _source_type_counts(sources: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for source in sources:
        source_type = str(source.get("source_type") or "context")
        counts[source_type] = counts.get(source_type, 0) + 1
    return counts
