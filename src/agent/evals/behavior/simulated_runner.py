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
from agent.evals.behavior.simulated_judge import ConversationJudge, IndependentJudgment
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
    independent_judgments: tuple[IndependentJudgment, ...] = ()


async def run_simulated_conversation(
    *,
    scenario: SimulatedUserScenario,
    simulated_user: SimulatedUser,
    companion: RuntimeDriverConfig,
    independent_judges: tuple[ConversationJudge, ...] = (),
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
    independent_judgments = await _run_independent_judges(
        judges=independent_judges,
        scenario=scenario,
        transcript=final_transcript,
        conversation_id=conversation_id,
        event_sink=event_sink,
    )
    consensus = _conversation_consensus(user_verdict, independent_judgments)
    emit_event(
        event_sink,
        "simulated_conversation_completed",
        "AI-user conversation and judgments completed.",
        scenario_id=scenario.id,
        turn_count=len(observed_turns),
        stop_reason=stop_reason,
        passed=consensus["passed"],
        verdict=consensus["verdict"],
    )
    return SimulatedConversationResult(
        scenario_id=scenario.id,
        turns=tuple(observed_turns),
        stop_reason=stop_reason,
        conversation_id=conversation_id,
        user_verdict=user_verdict,
        independent_judgments=independent_judgments,
    )


def simulated_conversation_payload(
    result: SimulatedConversationResult,
    *,
    simulated_user_provider: str,
    simulated_user_model: str,
) -> dict[str, Any]:
    independent_payload = [
        _independent_judgment_payload(judgment) for judgment in result.independent_judgments
    ]
    consensus = _conversation_consensus(result.user_verdict, result.independent_judgments)
    return {
        "stage": "simulated_conversation",
        "passed": consensus["passed"],
        "verdict": consensus["verdict"],
        "simulated_user": {
            "provider": simulated_user_provider,
            "model": simulated_user_model,
        },
        "judges": [
            f"AI user judge ({simulated_user_provider} / {simulated_user_model})",
            *(item["judge_name"] for item in independent_payload),
        ],
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
        "independent_judgments": independent_payload,
        "consensus": consensus,
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


def simulated_conversation_suite_payload(
    results: tuple[SimulatedConversationResult, ...],
    *,
    simulated_user_provider: str,
    simulated_user_model: str,
    selection: dict[str, Any],
) -> dict[str, Any]:
    conversations = [
        simulated_conversation_payload(
            result,
            simulated_user_provider=simulated_user_provider,
            simulated_user_model=simulated_user_model,
        )
        for result in results
    ]
    passed_count = sum(payload.get("passed") is True for payload in conversations)
    failed_count = sum(payload.get("passed") is False for payload in conversations)
    pending_count = sum(payload.get("passed") is None for payload in conversations)
    scores = [
        (payload.get("consensus") or {}).get("average_score")
        for payload in conversations
        if isinstance((payload.get("consensus") or {}).get("average_score"), (int, float))
    ]
    judge_names = list(
        dict.fromkeys(
            judge
            for payload in conversations
            for judge in payload.get("judges", [])
        )
    )
    return {
        "stage": "simulated_conversation_suite",
        "passed": bool(conversations) and failed_count == 0 and pending_count == 0,
        "verdict": "suite_pass" if conversations and failed_count == 0 and pending_count == 0 else "suite_fail",
        "selection": selection,
        "simulated_user": {
            "provider": simulated_user_provider,
            "model": simulated_user_model,
        },
        "judges": judge_names,
        "summary": {
            "total": len(conversations),
            "passed": passed_count,
            "failed": failed_count,
            "pending": pending_count,
            "average_score": round(sum(scores) / len(scores), 3) if scores else None,
        },
        "conversations": conversations,
    }


async def _run_independent_judges(
    *,
    judges: tuple[ConversationJudge, ...],
    scenario: SimulatedUserScenario,
    transcript: tuple[dict[str, str], ...],
    conversation_id: str,
    event_sink: EventSink | None,
) -> tuple[IndependentJudgment, ...]:
    judgments: list[IndependentJudgment] = []
    for judge in judges:
        emit_event(
            event_sink,
            "independent_judgment_started",
            "Independent judge started reviewing the completed conversation.",
            judge_name=judge.judge_name,
            scenario_id=scenario.id,
        )
        try:
            verdict = await judge.judge_conversation(
                scenario=scenario,
                transcript=transcript,
                conversation_id=conversation_id,
            )
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            judgments.append(IndependentJudgment(judge_name=judge.judge_name, error=message))
            emit_event(
                event_sink,
                "independent_judgment_failed",
                "Independent judge failed.",
                judge_name=judge.judge_name,
                scenario_id=scenario.id,
                error=message,
            )
            continue
        judgments.append(IndependentJudgment(judge_name=judge.judge_name, verdict=verdict))
        emit_event(
            event_sink,
            "independent_judgment_completed",
            "Independent judge finished reviewing the completed conversation.",
            judge_name=judge.judge_name,
            scenario_id=scenario.id,
            passed=verdict.passed,
            average_score=verdict.average_score,
            would_continue=verdict.would_continue,
            dimensions=[
                {
                    "dimension_id": grade.dimension_id,
                    "score": grade.score,
                    "reason": grade.reason,
                }
                for grade in verdict.grades
            ],
        )
    return tuple(judgments)


def _conversation_consensus(
    user_verdict: UserExperienceVerdict,
    independent_judgments: tuple[IndependentJudgment, ...],
) -> dict[str, Any]:
    voices: list[dict[str, Any]] = [
        {
            "name": "AI user judge",
            "passed": user_verdict.passed,
            "average_score": user_verdict.average_score,
            "error": None,
        }
    ]
    for judgment in independent_judgments:
        voices.append(
            {
                "name": judgment.judge_name,
                "passed": judgment.passed,
                "average_score": (
                    judgment.verdict.average_score if judgment.verdict is not None else None
                ),
                "error": judgment.error,
            }
        )
    judge_errors = sum(voice["error"] is not None for voice in voices)
    passing_voices = sum(bool(voice["passed"]) for voice in voices)
    has_independent = bool(independent_judgments)
    passed = has_independent and judge_errors == 0 and passing_voices == len(voices)
    verdict = "consensus_pass" if passed else "consensus_fail"
    disagreements = []
    if has_independent and len({bool(voice["passed"]) for voice in voices}) > 1:
        disagreements.append("AI-user and independent judge verdicts disagree.")
    if not has_independent:
        verdict = "pending_independent_judge"
    scores = [
        voice["average_score"]
        for voice in voices
        if isinstance(voice["average_score"], (int, float))
    ]
    return {
        "passed": passed if has_independent else None,
        "verdict": verdict,
        "average_score": round(sum(scores) / len(scores), 3) if scores else None,
        "required_voices": 2,
        "total_voices": len(voices),
        "passing_voices": passing_voices,
        "judge_errors": judge_errors,
        "disagreements": disagreements,
        "reason": _consensus_reason(has_independent, passed, judge_errors, disagreements),
    }


def _consensus_reason(
    has_independent: bool,
    passed: bool,
    judge_errors: int,
    disagreements: list[str],
) -> str:
    if not has_independent:
        return "The AI-user verdict exists, but no independent judge has reviewed the transcript yet."
    if judge_errors:
        return "At least one judge errored, so the consensus fails closed."
    if disagreements:
        return "The user and independent judge disagree, so this needs review before trusting it."
    if passed:
        return "The AI-user and independent judge both passed the conversation."
    return "At least one judging voice failed the conversation."


def _independent_judgment_payload(judgment: IndependentJudgment) -> dict[str, Any]:
    if judgment.verdict is None:
        return {
            "judge_name": judgment.judge_name,
            "passed": False,
            "error": judgment.error,
            "average_score": None,
            "would_continue": False,
            "overall_reason": "",
            "biggest_problem": judgment.error or "Independent judge failed.",
            "dimensions": [],
        }
    return {
        "judge_name": judgment.judge_name,
        "passed": judgment.verdict.passed,
        "error": None,
        "average_score": judgment.verdict.average_score,
        "would_continue": judgment.verdict.would_continue,
        "overall_reason": judgment.verdict.overall_reason,
        "biggest_problem": judgment.verdict.biggest_problem,
        "dimensions": [
            {
                "dimension_id": grade.dimension_id,
                "score": grade.score,
                "reason": grade.reason,
            }
            for grade in judgment.verdict.grades
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
