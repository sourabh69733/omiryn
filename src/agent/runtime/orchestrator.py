"""Coordinates one complete companion turn across context, models, memory, and traces."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from agent.context_engine.conversation_engine.policy import direct_turn_reply, split_assistant_reply
from agent.context_engine.conversation_engine.policy.freshness import (
    question_rule_reason,
    recent_assistant_replies,
    rewrite_instruction,
    stale_reply_reason,
)
from agent.config import agent_pipeline_config
from agent.context_engine.engine import build_model_context_package
from agent.memory_engine.engine import capture_profile_facts_from_user_message
from agent.memory_engine.memories.embeddings import embed_memory_query, memory_query_text
from agent.shared.clock import utc_now_iso
from agent.providers import (
    AgentProviderError,
    AgentProviderTruncationError,
    _prompt_debug,
    _provider_messages,
    assess_user_message_quality,
    generate_agent_reply,
)
from agent.providers.shared.messages import reply_window, summarized_through
from agent.outputs.companion_response import structured_companion_reply
from agent.context_engine.state.turn import assistant_turn_state
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

    # Stamped on arrival so gap notes and time context see when the user actually wrote.
    user_message: dict[str, Any] = {
        "role": "user",
        "content": user_text,
        "created_at": utc_now_iso(),
    }
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
    direct_reply = direct_turn_reply(user_text, updated_messages)
    if direct_reply:
        user_message["quality"] = direct_reply.quality
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
    if direct_reply:
        updated_messages.append({"role": "assistant", "content": direct_reply.reply})
        save_agent_trace_step(
            {
                "trace_id": trace_id,
                "user_id": user_id,
                "conversation_id": conversation_id,
                "step_index": 2,
                "step_name": "turn_policy",
                "status": "direct_reply",
                "metadata": {
                    "reason": direct_reply.reason,
                    "confidence": direct_reply.confidence,
                    "reply_chars": len(direct_reply.reply),
                    "skipped_model_call": True,
                    "skipped_context_pack": True,
                },
            }
        )
        finish_agent_trace(
            trace_id,
            status="completed",
            summary={
                "ending_message_count": len(updated_messages),
                "quality_valid": quality_valid,
                "reply_chars": len(direct_reply.reply),
                "reply_part_count": 1,
                "direct_reply": True,
                "turn_policy_reason": direct_reply.reason,
            },
        )
        return AgentTurnResult(messages=updated_messages, quality_valid=quality_valid)

    context_arguments = {
        "conversation_id": conversation_id,
        "user_text": user_text,
        "user_id": user_id,
        "user_profile": user_profile,
        "model": model,
        "agent_tone": agent_tone,
        "agent_name": agent_name,
        "style_source_id": style_source_id,
        "user_message_index": len(updated_messages) - 1,
        "assistant_message_index": len(updated_messages),
    }
    if agent_pipeline_config().memory_contract_version == 3:
        context_arguments["memory_query_embedding"] = await embed_memory_query(
            memory_query_text(user_text, messages), conversation_id=conversation_id
        )
    context_package = build_model_context_package(**context_arguments)
    system_prompt = context_package.system_prompt
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
    # Older messages the background summary already covers stay out of the chat history.
    reply_messages = reply_window(
        updated_messages,
        summarized_through(context_package.context_sources),
        (context_package.user_profile or {}).get("timezone"),
    )
    # The last thing the model reads; it follows this more reliably than rules in the prompt.
    reply_messages = reply_messages + _turn_notes(context_package.question_limit)
    provider_messages = _provider_messages(reply_messages)
    if context_snapshot:
        context_snapshot.setdefault("context", {})["prompt"] = {
            "system_prompt": system_prompt,
            "provider_messages": provider_messages,
            "prompt_debug": _prompt_debug(system_prompt, provider_messages),
        }
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
        generation_arguments = {
            "conversation_id": conversation_id,
            "model": model,
            "agent_mode": agent_mode,
            "agent_tone": agent_tone,
            "agent_name": agent_name,
            "context_sources": context_package.context_sources,
            "user_profile": context_package.user_profile,
            "system_prompt": system_prompt,
        }
        fallback_reason = None
        try:
            raw_reply = await generate_agent_reply(
                reply_messages,
                **generation_arguments,
            )
        except AgentProviderTruncationError:
            fallback_reason = "output_truncated"
            raw_reply = await generate_agent_reply(
                reply_messages,
                **generation_arguments,
                max_tokens=400,
            )

        sanitized_structured_reply = structured_companion_reply(raw_reply)
        if (
            fallback_reason is None
            and sanitized_structured_reply is None
            and _looks_like_model_transport(raw_reply)
        ):
            fallback_reason = "malformed_structured_output"
            raw_reply = await generate_agent_reply(
                reply_messages,
                **generation_arguments,
                max_tokens=400,
            )
            sanitized_structured_reply = structured_companion_reply(raw_reply)

        reply = _visible_companion_reply(raw_reply, sanitized_structured_reply)
        reply, freshness = await _freshen_reply(
            reply,
            previous_replies=recent_assistant_replies(messages),
            reply_messages=reply_messages,
            generation_arguments=generation_arguments,
            question_limit=context_package.question_limit,
        )
        reply_parts = split_assistant_reply(reply, user_text=user_text)
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
                "reply_part_count": len(reply_parts),
                "model": model,
                "prompt_version": context_package.prompt_version,
                "agent_mode": agent_mode,
                "agent_tone": agent_tone,
                "foreground_contract": "reply_only",
                "fallback_reason": fallback_reason,
                "freshness": freshness,
            },
        }
    )
    for index, reply_part in enumerate(reply_parts):
        assistant_message = {"role": "assistant", "content": reply_part}
        turn_state = assistant_turn_state(
            reply_part,
            conversation_move=(context_snapshot.get("summary") or {}).get("conversation_move"),
            response_mode=(context_snapshot.get("summary") or {}).get("response_mode"),
        )
        if turn_state and index == len(reply_parts) - 1:
            assistant_message["turn_state"] = turn_state
        updated_messages.append(assistant_message)
    if context_snapshot:
        context_snapshot.setdefault("context", {}).setdefault("prompt", {})["assistant_reply"] = (
            reply
        )
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
            "reply_part_count": len(reply_parts),
        },
    )
    return AgentTurnResult(messages=updated_messages, quality_valid=quality_valid)


async def _freshen_reply(
    reply: str,
    *,
    previous_replies: list[str],
    reply_messages: list[dict[str, Any]],
    generation_arguments: dict[str, Any],
    question_limit: int = 1,
) -> tuple[str, dict[str, Any] | None]:
    """Ask for one rewrite when the draft breaks the question limit, is stock filler, or
    repeats itself.

    The rewrite is best effort: any failure keeps the original draft.
    """
    if not freshness_check_enabled():
        return reply, None

    def problem(text: str) -> str | None:
        return question_rule_reason(text, question_limit) or stale_reply_reason(
            text, previous_replies
        )

    reason = problem(reply)
    if reason is None:
        return reply, None
    try:
        raw = await generate_agent_reply(
            reply_messages,
            **{
                **generation_arguments,
                "system_prompt": generation_arguments["system_prompt"]
                + rewrite_instruction(reply, reason),
            },
        )
        rewritten = _visible_companion_reply(raw, structured_companion_reply(raw))
    except Exception as error:
        return reply, {"reason": reason, "rewritten": False, "error": type(error).__name__}
    if not rewritten.strip():
        return reply, {"reason": reason, "rewritten": False}
    return rewritten, {
        "reason": reason,
        "rewritten": True,
        "still_stale": problem(rewritten) is not None,
    }


_NO_QUESTION_NOTE = (
    "For this reply: react to what the user said or share a thought. Do not ask any question."
)


def _turn_notes(question_limit: int) -> list[dict[str, str]]:
    """Per-turn rules placed after the user's message."""
    if question_limit == 0:
        return [{"role": "system", "content": _NO_QUESTION_NOTE}]
    return []


def freshness_check_enabled() -> bool:
    return os.getenv("AGENT_FRESHNESS_CHECK", "true").strip().lower() != "false"


def _source_type_counts(sources: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for source in sources:
        source_type = str(source.get("source_type") or "context")
        counts[source_type] = counts.get(source_type, 0) + 1
    return counts


def _looks_like_model_transport(raw_text: str) -> bool:
    """Identify private JSON/tool syntax that must not be rendered as companion text."""
    text = str(raw_text or "").lstrip().casefold()
    return text.startswith("{") or text.startswith("```json") or "<function" in text


def _visible_companion_reply(raw_text: str, decoded_reply: str | None = None) -> str:
    """Return only user-visible prose, rejecting undecodable private transport output."""
    if decoded_reply:
        return decoded_reply
    if _looks_like_model_transport(raw_text):
        raise AgentProviderError("Model returned an undecodable private response envelope.")
    return str(raw_text or "").strip()
