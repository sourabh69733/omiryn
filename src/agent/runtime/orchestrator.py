"""Coordinates one complete companion turn across context, models, memory, and traces."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from agent.context_engine.conversation_engine.policy import direct_turn_reply, split_assistant_reply
from agent.context_engine.conversation_engine.policy.replies import (
    STORY_END_MARKER,
    STORY_MARKER,
    STORY_NOTE_PREFIX,
    strip_story_end,
    strip_story_marker,
    strip_voice_marker,
)
from agent.runtime.story_mode import (
    schedule_story_part,
    story_autoplay_enabled,
    story_part_block_reason,
)
from agent.context_engine.conversation_engine.policy.freshness import (
    question_rule_reason,
    recent_assistant_replies,
    rewrite_instruction,
    stale_reply_reason,
    trim_questions,
    without_copied_replies,
)
from agent.context_engine.conversation_engine.policy.requests import (
    broken_requests,
    broken_requests_reason,
    how_to_talk_requests,
    request_check_input,
)
from agent.config import agent_pipeline_config
from agent.context_engine.engine import build_model_context_package
from agent.memory_engine.engine import capture_profile_facts_from_user_message
from agent.memory_engine.memories.embeddings import embed_memory_query, memory_query_text
from agent.shared.clock import utc_now_iso
from agent.providers import (
    AgentProviderError,
    check_reply_requests,
    AgentProviderTruncationError,
    _provider_messages,
    assess_user_message_quality,
    generate_agent_reply,
)
from agent.providers.shared.messages import reply_window, summarized_through
from agent.providers.gateway.clients import parse_tool_call
from agent.memory_engine.search import SEARCH_TOOL, search_chats, search_note
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
        **({"reply_to": reply_to} if reply_to else {}),
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
    reply_messages = reply_messages + _turn_notes(
        context_package.question_limit,
        context_package.query_intent.labels if context_package.query_intent else (),
        unanswered_count,
    )
    provider_messages = _provider_messages(reply_messages)
    save_agent_trace_step(
        {
            "trace_id": trace_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "step_index": 3,
            "step_name": "context_pack",
            "status": "ok",
            "metadata": {
                "included_source_count": (context_snapshot.get("summary") or {}).get("included_source_count"),
                "rough_context_tokens": (context_snapshot.get("summary") or {}).get("rough_context_tokens"),
            },
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
        chat_search: dict[str, Any] | None = None
        try:
            raw_reply = await generate_agent_reply(
                reply_messages,
                **generation_arguments,
                **(_search_tool_arguments() if user_id and chat_search_enabled() else {}),
            )
            raw_reply, chat_search = await _answer_with_search(
                raw_reply, user_id=user_id, reply_messages=reply_messages, generation_arguments=generation_arguments
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
        reply, request_check = await _follow_requests(
            reply,
            requests=how_to_talk_requests(context_package.context_sources),
            reply_messages=reply_messages,
            generation_arguments=generation_arguments,
            question_limit=context_package.question_limit,
        )
        reply, story_ended = strip_story_end(reply)
        reply, story_marked = strip_story_marker(reply)
        reply, requested_voice = strip_voice_marker(reply)
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
                "request_check": request_check,
                "chat_search": chat_search,
            },
        }
    )
    # The model's own marker decides; a keyword in the user's message is only a hint for the note.
    story_turn = story_marked or story_ended
    for index, reply_part in enumerate(reply_parts):
        assistant_message = {"role": "assistant", "content": reply_part}
        if story_turn:
            assistant_message["story"] = True  # lets "then?" next turn continue the story
        turn_state = assistant_turn_state(
            reply_part,
            conversation_move=(context_snapshot.get("summary") or {}).get("conversation_move"),
            response_mode=(context_snapshot.get("summary") or {}).get("response_mode"),
        )
        if turn_state and index == len(reply_parts) - 1:
            assistant_message["turn_state"] = turn_state
        if story_turn and story_ended and index == len(reply_parts) - 1:
            assistant_message["story_end"] = True
        updated_messages.append(assistant_message)
    if (
        story_turn
        and user_id
        and story_autoplay_enabled()
        and story_part_block_reason(updated_messages) is None
    ):
        # The user is listening; the next part follows on its own unless they write first.
        schedule_story_part(user_id, conversation_id)
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
    return AgentTurnResult(
        messages=updated_messages, quality_valid=quality_valid, agent_voice=requested_voice
    )


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
        # The note goes last, where the model follows it best, and the replies the draft copied
        # leave the history so the rewrite cannot copy them again.
        history = without_copied_replies(reply_messages, reply)
        note = rewrite_instruction(reply, reason, quote_draft=len(history) == len(reply_messages))
        raw = await generate_agent_reply(
            history + [{"role": "system", "content": note}], **generation_arguments
        )
        rewritten = _visible_companion_reply(raw, structured_companion_reply(raw))
    except Exception as error:
        return reply, {"reason": reason, "rewritten": False, "error": type(error).__name__}
    if not rewritten.strip():
        return reply, {"reason": reason, "rewritten": False}
    trimmed = False
    if question_rule_reason(rewritten, question_limit):
        # The model tends to copy the questions in its own history, even when asked not to.
        rewritten = trim_questions(rewritten, question_limit)
        trimmed = True
    return rewritten, {
        "reason": reason,
        "rewritten": True,
        "questions_trimmed": trimmed,
        "still_stale": problem(rewritten) is not None,
    }


def chat_search_enabled() -> bool:
    return os.getenv("AGENT_CHAT_SEARCH", "true").strip().lower() != "false"


def _search_tool_arguments() -> dict[str, Any]:
    return {"tools": [SEARCH_TOOL], "tool_choice": "auto"}


async def _answer_with_search(
    raw_reply: str,
    *,
    user_id: str | None,
    reply_messages: list[dict[str, Any]],
    generation_arguments: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """When the reply model asked to search past chats: run it, then reply from the real lines.

    The search runs only when the model calls it, so other replies cost nothing extra. The second
    call has no tools, so it always ends in a reply.
    """
    called = parse_tool_call(raw_reply)
    if called is None or not user_id:
        return raw_reply, None
    name, arguments = called
    query = str(arguments.get("query") or "").strip()[:200]
    person = str(arguments.get("person") or "").strip()[:80] or None
    days = arguments.get("days") if isinstance(arguments.get("days"), int) and arguments.get("days") > 0 else None
    hits = search_chats(user_id, query, person=person, days=days) if name == SEARCH_TOOL["function"]["name"] else []
    note = search_note(query, person, days, hits)
    reply = await generate_agent_reply(reply_messages + [{"role": "system", "content": note}], **generation_arguments)
    return reply, {"tool": name, "query": query, "person": person, "days": days, "hits": len(hits)}


async def _follow_requests(
    reply: str,
    *,
    requests: list[str],
    reply_messages: list[dict[str, Any]],
    generation_arguments: dict[str, Any],
    question_limit: int = 1,
) -> tuple[str, dict[str, Any] | None]:
    """One rewrite when the draft breaks how the user asked to be talked to.

    Runs only for users with saved how-to-talk requests. Best effort: any failure keeps the draft.
    """
    if not requests or not request_check_enabled():
        return reply, None
    conversation_id = str(generation_arguments.get("conversation_id") or "")
    try:
        raw = await check_reply_requests(request_check_input(reply, requests), conversation_id=conversation_id)
    except Exception as error:
        return reply, {"checked": False, "error": type(error).__name__}
    broken = broken_requests(raw, requests)
    if not broken:
        return reply, {"checked": True, "broken": []}
    try:
        note = rewrite_instruction(reply, broken_requests_reason(broken), keep_length=False)
        raw_reply = await generate_agent_reply(
            reply_messages + [{"role": "system", "content": note}], **generation_arguments
        )
        rewritten = _visible_companion_reply(raw_reply, structured_companion_reply(raw_reply))
    except Exception as error:
        return reply, {"checked": True, "broken": broken, "rewritten": False, "error": type(error).__name__}
    if not rewritten.strip():
        return reply, {"checked": True, "broken": broken, "rewritten": False}
    if question_rule_reason(rewritten, question_limit):
        rewritten = trim_questions(rewritten, question_limit)
    return rewritten, {"checked": True, "broken": broken, "rewritten": True}


def request_check_enabled() -> bool:
    return os.getenv("AGENT_REQUEST_CHECK", "true").strip().lower() != "false"


_NO_QUESTION_NOTE = (
    "For this reply: react to what the user said or share a thought. Do not ask any question."
)


_STORY_NOTE = (
    f"{STORY_NOTE_PREFIX} the user asked for a story. Start with {STORY_MARKER} and tell it yourself now in 4-7 short bubbles "
    "separated by <next_message>: a character, a setting and something that happens. Do not ask "
    "the user what should happen."
)
_STORY_CONTINUE_NOTE = (
    f"{STORY_NOTE_PREFIX} the user is following the story you are telling. If they react or ask "
    f"for more, start with {STORY_MARKER}, react in a few words at most, then continue the story from where it stopped in 3-7 "
    "short bubbles separated by <next_message>. Move the plot forward; do not restart or recap. "
    "If they want to stop or have moved on to something else, reply to that instead and add "
    f"{STORY_END_MARKER} at the very end."
)
_STORY_ENDING = " End with an ending or a light 'want more?'."
# With autoplay the story goes on by itself, so a part stops at a pause instead of asking.
_STORY_AUTOPLAY_ENDING = (
    " Stop this part at a natural pause without asking whether to go on; you will continue on "
    f"your own in a moment. When the whole story is finished, add {STORY_END_MARKER} at the very end."
)


_UNANSWERED_NOTE = (
    "The user sent their last {count} messages in a row before you replied. Read them together "
    "and reply once: answer each one that needs an answer, in its own short bubble, and let "
    "greetings or fillers pass without a bubble of their own."
)


def _turn_notes(
    question_limit: int, intent_labels: tuple[str, ...] = (), unanswered_count: int = 1
) -> list[dict[str, str]]:
    """Per-turn rules placed after the user's message."""
    notes = []
    if unanswered_count > 1:
        notes.append({"role": "system", "content": _UNANSWERED_NOTE.format(count=unanswered_count)})
    ending = _STORY_AUTOPLAY_ENDING if story_autoplay_enabled() else _STORY_ENDING
    if "story_continuation" in intent_labels:
        notes.append({"role": "system", "content": _STORY_CONTINUE_NOTE + ending})
    elif "story_or_long_reply" in intent_labels:
        notes.append({"role": "system", "content": _STORY_NOTE + ending})
    elif question_limit == 0:
        notes.append({"role": "system", "content": _NO_QUESTION_NOTE})
    return notes


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
