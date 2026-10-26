"""Coordinates one complete companion turn: guard the input, build the context, run the reply
steps (`runtime/steps`), save the messages and trace every stage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.config import agent_pipeline_config
from agent.context_engine.policy import direct_turn_reply
from agent.context_engine.policy.freshness import recent_assistant_replies
from agent.context_engine.policy.requests import how_to_talk_requests
from agent.context_engine.engine import build_model_context_package
from agent.memory_engine.engine import capture_profile_facts_from_user_message
from agent.memory_engine.memories.embeddings import embed_memory_query, memory_query_text
from agent.providers import assess_user_message_quality, generate_agent_reply
from agent.providers.shared.messages import reply_window, summarized_through
from agent.runtime.steps import REPLY_CHECKS, ReplyJob, assistant_messages, finish_reply, turn_notes, write_draft
from agent.runtime.story_mode import schedule_story_part, story_autoplay_enabled, story_part_block_reason
from agent.shared.clock import utc_now_iso
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
    # Set when the user asked the companion to change how it talks (neutral, female, male).
    agent_voice: str | None = None


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
    reply_to: dict[str, Any] | None = None,
    unanswered_count: int = 1,
) -> AgentTurnResult:
    """`unanswered_count` > 1: the user sent several messages in a row (on a messaging app);
    the earlier ones are the last items of `messages` and this reply answers them all."""
    updated_messages = [dict(message) for message in messages]
    saved = save_agent_trace(
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
    trace = _TurnTrace(saved["id"], user_id, conversation_id)

    # 1. Input: stamped on arrival so gap notes and time context see when the user actually wrote.
    user_message: dict[str, Any] = {
        "role": "user",
        "content": user_text,
        "created_at": utc_now_iso(),
        **({"reply_to": reply_to} if reply_to else {}),
    }
    quality = assess_user_message_quality(updated_messages + [user_message])
    quality_valid = bool(quality["valid"])
    if not quality_valid:
        user_message["quality"] = "low_information"
    trace.step(0, "input_guardrail", "ok" if quality_valid else "blocked", {
        "quality_valid": quality_valid,
        "message_chars": len(user_text),
        "reply_provided": bool(quality.get("reply")),
    })

    updated_messages.append(user_message)
    direct_reply = direct_turn_reply(user_text, updated_messages)
    if direct_reply:
        user_message["quality"] = direct_reply.quality
    capture_profile_facts_from_user_message(conversation_id, user_id, user_text, len(updated_messages) - 1, quality_valid)
    trace.step(1, "memory_write", "ok" if user_id and quality_valid else "skipped", {
        "user_scoped": bool(user_id),
        "quality_valid": quality_valid,
        "source_kind": "agent_chat",
    })

    # 2. A reply that needs no model (a policy answer).
    if direct_reply:
        updated_messages.append({"role": "assistant", "content": direct_reply.reply})
        trace.step(2, "turn_policy", "direct_reply", {
            "reason": direct_reply.reason,
            "confidence": direct_reply.confidence,
            "reply_chars": len(direct_reply.reply),
            "skipped_model_call": True,
            "skipped_context_pack": True,
        })
        finish_agent_trace(
            trace.id,
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

    # 3. Context: what the model reads besides the chat.
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
    trace.step(2, "retrieval", "ok", {
        "source_count": len(context_package.context_sources),
        "source_types": _source_type_counts(context_package.context_sources),
        "has_user_profile": bool(context_package.user_profile),
        "query_intent": list(context_package.query_intent.labels) if context_package.query_intent else [],
    })
    context_snapshot = context_package.snapshot or {}
    context_summary = context_snapshot.get("summary") or {}
    # Older messages the background summary already covers stay out of the chat history.
    reply_messages = reply_window(
        updated_messages,
        summarized_through(context_package.context_sources),
        (context_package.user_profile or {}).get("timezone"),
    )
    reply_messages = reply_messages + turn_notes(
        context_package.question_limit,
        context_package.query_intent.labels if context_package.query_intent else (),
        unanswered_count,
    )
    trace.step(3, "context_pack", "ok", {
        "included_source_count": context_summary.get("included_source_count"),
        "rough_context_tokens": context_summary.get("rough_context_tokens"),
    })

    # 4. The reply steps: draft, checks, finish.
    job = ReplyJob(
        reply_messages=reply_messages,
        generation_arguments={
            "conversation_id": conversation_id,
            "model": model,
            "agent_mode": agent_mode,
            "agent_tone": agent_tone,
            "agent_name": agent_name,
            "context_sources": context_package.context_sources,
            "user_profile": context_package.user_profile,
            "system_prompt": context_package.system_prompt,
        },
        # Looked up at call time, so the client can be swapped in one place.
        generate=lambda *args, **kwargs: generate_agent_reply(*args, **kwargs),
        question_limit=context_package.question_limit,
        user_id=user_id,
        conversation_id=conversation_id,
        user_text=user_text,
        history=messages,
        previous_replies=recent_assistant_replies(messages),
        requests=how_to_talk_requests(context_package.context_sources),
    )
    try:
        draft = await write_draft(job)
        reply, checks = draft.reply, {}
        for name, check in REPLY_CHECKS:
            reply, checks[name] = await check(reply, job)
        finished = finish_reply(reply, user_text)
    except Exception as error:
        trace.step(4, "model_call", "failed", {"error_type": type(error).__name__})
        finish_agent_trace(trace.id, status="failed", summary={"error_type": type(error).__name__})
        raise
    trace.step(4, "model_call", "ok", {
        "reply_chars": len(finished.text),
        "reply_part_count": len(finished.parts),
        "model": model,
        "prompt_version": context_package.prompt_version,
        "agent_mode": agent_mode,
        "agent_tone": agent_tone,
        "foreground_contract": "reply_only",
        "fallback_reason": draft.fallback_reason,
        **checks,
        "chat_search": draft.chat_search,
        "tool_calls": draft.tool_calls,
    })

    # 5. Save the bubbles, maybe the next story part, and the context snapshot.
    updated_messages.extend(assistant_messages(finished, context_summary))
    if finished.story and user_id and story_autoplay_enabled() and story_part_block_reason(updated_messages) is None:
        # The user is listening; the next part follows on its own unless they write first.
        schedule_story_part(user_id, conversation_id)
    save_agent_context_snapshot(context_snapshot)
    trace.step(5, "context_snapshot", "ok", {
        "message_index": context_snapshot["message_index"],
        "included_source_count": context_snapshot["summary"].get("included_source_count"),
        "rough_context_tokens": context_snapshot["summary"].get("rough_context_tokens"),
    })
    finish_agent_trace(
        trace.id,
        status="completed",
        summary={
            "ending_message_count": len(updated_messages),
            "quality_valid": quality_valid,
            "reply_chars": len(finished.text),
            "reply_part_count": len(finished.parts),
        },
    )
    return AgentTurnResult(messages=updated_messages, quality_valid=quality_valid, agent_voice=finished.voice)


@dataclass(frozen=True)
class _TurnTrace:
    """Saves the steps of one turn's trace."""

    id: str
    user_id: str | None
    conversation_id: str

    def step(self, index: int, name: str, status: str, metadata: dict[str, Any]) -> None:
        save_agent_trace_step({
            "trace_id": self.id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "step_index": index,
            "step_name": name,
            "status": status,
            "metadata": metadata,
        })


def _source_type_counts(sources: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for source in sources:
        source_type = str(source.get("source_type") or "context")
        counts[source_type] = counts.get(source_type, 0) + 1
    return counts
