from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from agent.evals.behavior.events import EventSink, emit_event
from agent.evals.behavior.models import ObservedTurn
from agent.evals.behavior.runtime_driver import (
    RuntimeDriverConfig,
    _conversation_payload,
    _direct_reply_reason,
    _runtime_environment,
)
from agent.evals.behavior.simulated_user import (
    SimulatedUser,
    SimulatedUserScenario,
    UserExperienceVerdict,
)
from agent.runtime.orchestrator import run_agent_turn
from storage import (
    list_agent_context_snapshots,
    list_agent_trace_steps,
    list_agent_traces,
    save_conversation,
)


@dataclass(frozen=True)
class SimulatedConversationResult:
    scenario_id: str
    turns: tuple[ObservedTurn, ...]
    stop_reason: str
    conversation_id: str
    user_verdict: UserExperienceVerdict


async def run_simulated_conversation(
    *,
    scenario: SimulatedUserScenario,
    simulated_user: SimulatedUser,
    companion: RuntimeDriverConfig,
    event_sink: EventSink | None = None,
) -> SimulatedConversationResult:
    user_id = f"ai-user-eval-{scenario.id}-{uuid4().hex[:8]}"
    conversation_id = f"ai-user-eval-conversation-{uuid4().hex}"
    messages: list[dict[str, Any]] = []
    profile = {"user_id": user_id, **scenario.user_profile}
    save_conversation(
        _conversation_payload(
            conversation_id=conversation_id,
            user_id=user_id,
            messages=messages,
            config=companion,
        ),
        user_id,
    )
    emit_event(
        event_sink,
        "simulated_conversation_started",
        "AI-user conversation started.",
        scenario_id=scenario.id,
        maximum_turns=scenario.maximum_turns,
    )
    observed_turns: list[ObservedTurn] = []
    stop_reason = "maximum_turns"
    with _runtime_environment(companion):
        for turn_index in range(scenario.maximum_turns):
            transcript = tuple(
                {"role": str(item.get("role") or ""), "content": str(item.get("content") or "")}
                for item in messages
                if item.get("role") in {"user", "assistant"}
            )
            decision = await simulated_user.next_turn(
                scenario=scenario,
                transcript=transcript,
                turn_index=turn_index,
                conversation_id=conversation_id,
            )
            if decision.action == "finish":
                stop_reason = "ai_user_finished"
                emit_event(
                    event_sink,
                    "simulated_user_finished",
                    "AI user ended the conversation.",
                    turn_index=turn_index,
                )
                break
            assert decision.message is not None
            user_message = decision.message
            emit_event(
                event_sink,
                "user_turn",
                "Synthetic AI user turn started.",
                scenario_id=scenario.id,
                sample_index=0,
                turn_index=turn_index,
                message=user_message,
                speaker_label="AI User",
            )
            prior_message_count = len(messages)
            emit_event(
                event_sink,
                "companion_call_started",
                "Companion model call started.",
                scenario_id=scenario.id,
                sample_index=0,
                turn_index=turn_index,
                model_name=companion.model or f"{companion.provider} default",
            )
            try:
                result = await run_agent_turn(
                    conversation_id=conversation_id,
                    messages=messages,
                    user_text=user_message,
                    user_id=user_id,
                    user_profile=profile,
                    model=companion.model,
                    agent_mode=companion.agent_mode,
                    agent_tone=companion.agent_tone,
                    style_source_id=None,
                    agent_name=companion.agent_name,
                )
            except Exception as error:
                emit_event(
                    event_sink,
                    "companion_call_failed",
                    "Companion model call failed.",
                    scenario_id=scenario.id,
                    sample_index=0,
                    turn_index=turn_index,
                    error=f"{type(error).__name__}: {error}",
                )
                raise
            messages = result.messages
            assistant_messages = tuple(
                str(message.get("content") or "")
                for message in messages[prior_message_count + 1 :]
                if message.get("role") == "assistant"
            )
            trace_steps, context_summary = _runtime_debug(conversation_id, user_id)
            observed = ObservedTurn(
                turn_index=turn_index,
                user_message=user_message,
                assistant_reply=" ".join(assistant_messages).strip(),
                assistant_messages=assistant_messages,
                trace_steps=tuple(str(step["step_name"]) for step in trace_steps),
                direct_reply_reason=_direct_reply_reason(trace_steps),
                context_summary=context_summary,
                conversation_id=conversation_id,
                user_id=user_id,
            )
            observed_turns.append(observed)
            if "model_call" in observed.trace_steps:
                emit_event(
                    event_sink,
                    "companion_api_call_completed",
                    "Companion provider call completed.",
                    scenario_id=scenario.id,
                    sample_index=0,
                    turn_index=turn_index,
                    model_name=companion.model or f"{companion.provider} default",
                )
            emit_event(
                event_sink,
                "companion_turn",
                "Companion turn completed.",
                scenario_id=scenario.id,
                sample_index=0,
                turn_index=turn_index,
                message=observed.assistant_reply,
            )
            save_conversation(
                _conversation_payload(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    messages=messages,
                    config=companion,
                ),
                user_id,
            )
    final_transcript = tuple(
        {"role": str(item.get("role") or ""), "content": str(item.get("content") or "")}
        for item in messages
        if item.get("role") in {"user", "assistant"}
    )
    emit_event(
        event_sink,
        "user_judgment_started",
        "AI user started judging the completed conversation.",
        scenario_id=scenario.id,
        turn_count=len(observed_turns),
    )
    user_verdict = await simulated_user.judge_conversation(
        scenario=scenario,
        transcript=final_transcript,
        conversation_id=conversation_id,
    )
    emit_event(
        event_sink,
        "user_judgment_completed",
        "AI user finished judging the completed conversation.",
        scenario_id=scenario.id,
        passed=user_verdict.passed,
        average_score=user_verdict.average_score,
        would_continue=user_verdict.would_continue,
        dimensions=[
            {
                "dimension_id": grade.dimension_id,
                "score": grade.score,
                "reason": grade.reason,
            }
            for grade in user_verdict.grades
        ],
    )
    emit_event(
        event_sink,
        "simulated_conversation_completed",
        "AI-user conversation and user judgment completed; independent judgment is pending.",
        scenario_id=scenario.id,
        turn_count=len(observed_turns),
        stop_reason=stop_reason,
    )
    return SimulatedConversationResult(
        scenario_id=scenario.id,
        turns=tuple(observed_turns),
        stop_reason=stop_reason,
        conversation_id=conversation_id,
        user_verdict=user_verdict,
    )


def simulated_conversation_payload(
    result: SimulatedConversationResult,
    *,
    simulated_user_provider: str,
    simulated_user_model: str,
) -> dict[str, Any]:
    return {
        "stage": "simulated_conversation",
        "passed": None,
        "verdict": "pending_independent_judge",
        "simulated_user": {
            "provider": simulated_user_provider,
            "model": simulated_user_model,
        },
        "judges": [f"AI user judge ({simulated_user_provider} / {simulated_user_model})"],
        "user_judgment": {
            "passed": result.user_verdict.passed,
            "average_score": result.user_verdict.average_score,
            "would_continue": result.user_verdict.would_continue,
            "overall_reason": result.user_verdict.overall_reason,
            "biggest_problem": result.user_verdict.biggest_problem,
            "dimensions": [
                {
                    "dimension_id": grade.dimension_id,
                    "score": grade.score,
                    "reason": grade.reason,
                }
                for grade in result.user_verdict.grades
            ],
        },
        "conversations": [
            {
                "scenario_id": result.scenario_id,
                "stop_reason": result.stop_reason,
                "turns": [
                    {
                        "turn_index": turn.turn_index,
                        "user_message": turn.user_message,
                        "assistant_reply": turn.assistant_reply,
                    }
                    for turn in result.turns
                ],
            }
        ],
    }


def _runtime_debug(
    conversation_id: str,
    user_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    traces = list_agent_traces(conversation_id, user_id, limit=1)
    trace_steps = (
        list_agent_trace_steps(trace_id=traces[0]["id"], user_id=user_id) if traces else []
    )
    snapshots = list_agent_context_snapshots(conversation_id, user_id)
    has_snapshot_step = any(step.get("step_name") == "context_snapshot" for step in trace_steps)
    context_summary = (
        dict(snapshots[0].get("summary") or {}) if has_snapshot_step and snapshots else {}
    )
    return trace_steps, context_summary
