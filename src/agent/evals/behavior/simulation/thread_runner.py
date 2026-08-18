"""Runs thread scenarios through the real companion and grades shadow proposals."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator
from uuid import uuid4

from agent.context_engine.conversation_engine.state import (
    ConversationState,
    create_thread,
    save_state,
)
from agent.evals.behavior.core.events import EventSink, emit_event
from agent.evals.behavior.simulation.runtime import RuntimeDriverConfig, _conversation_payload
from agent.evals.behavior.simulation.thread_scenario import (
    ExpectedThreadAction,
    ThreadManagementScenario,
)
from agent.runtime.orchestrator import run_agent_turn
from storage import (
    list_agent_trace_steps,
    list_agent_traces,
    save_conversation,
)


@dataclass(frozen=True)
class ThreadScenarioResult:
    """One expected-versus-observed thread proposal result."""

    scenario_id: str
    passed: bool
    assistant_reply: str
    expected_operation: str
    actual_operations: tuple[str, ...]
    shadow_present: bool
    shadow_valid: bool
    proposal: dict[str, Any] | None
    validation_errors: tuple[str, ...]
    finding: str
    conversation_id: str


async def run_thread_management_scenario(
    *,
    scenario: ThreadManagementScenario,
    companion: RuntimeDriverConfig,
    event_sink: EventSink | None = None,
) -> ThreadScenarioResult:
    """Run one scenario without applying the model's proposed thread changes."""
    run_token = uuid4().hex
    user_id = f"thread-eval-{scenario.id}-{run_token[:8]}"
    conversation_id = f"thread-eval-conversation-{run_token}"
    messages = [dict(message) for message in scenario.prior_messages]
    profile = {
        "user_id": user_id,
        "display_name": "Thread Eval User",
        "gender": "unknown",
        "interested_in": "unknown",
    }
    save_conversation(
        _conversation_payload(
            conversation_id=conversation_id,
            user_id=user_id,
            messages=messages,
            config=companion,
        ),
        user_id,
    )
    fixture_ids = _create_thread_fixtures(
        scenario=scenario,
        user_id=user_id,
        conversation_id=conversation_id,
        companion=companion,
    )

    emit_event(
        event_sink,
        "thread_scenario_started",
        "Thread-management scenario started.",
        scenario_id=scenario.id,
        expected_operation=(
            scenario.expected_action.operation if scenario.expected_action else "none"
        ),
    )
    emit_event(
        event_sink,
        "user_turn",
        "Synthetic user turn started.",
        scenario_id=scenario.id,
        message=scenario.user_message,
    )
    emit_event(
        event_sink,
        "companion_call_started",
        "Companion model call started.",
        scenario_id=scenario.id,
        model_name=companion.model or f"{companion.provider} default",
    )
    with _thread_eval_environment(companion):
        try:
            result = await run_agent_turn(
                conversation_id=conversation_id,
                messages=messages,
                user_text=scenario.user_message,
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
                "Companion call failed.",
                scenario_id=scenario.id,
                error=f"{type(error).__name__}: {error}",
            )
            raise

    assistant_reply = " ".join(
        str(message.get("content") or "")
        for message in result.messages[len(messages) + 1 :]
        if message.get("role") == "assistant"
    ).strip()
    shadow = _latest_shadow_result(conversation_id=conversation_id, user_id=user_id)
    if shadow.get("model_called"):
        emit_event(
            event_sink,
            "companion_api_call_completed",
            "Companion provider call completed.",
            scenario_id=scenario.id,
            model_name=companion.model or f"{companion.provider} default",
        )
    emit_event(
        event_sink,
        "companion_turn",
        "Companion turn completed.",
        scenario_id=scenario.id,
        message=assistant_reply,
    )
    passed, finding = _grade_shadow_proposal(
        expected=scenario.expected_action,
        shadow=shadow,
        fixture_ids=fixture_ids,
    )
    proposal = shadow.get("proposal") if isinstance(shadow.get("proposal"), dict) else None
    operations = tuple(
        str(update.get("operation"))
        for update in (proposal or {}).get("thread_updates", [])
        if isinstance(update, dict) and update.get("operation")
    )
    scenario_result = ThreadScenarioResult(
        scenario_id=scenario.id,
        passed=passed,
        assistant_reply=assistant_reply,
        expected_operation=scenario.expected_action.operation if scenario.expected_action else "none",
        actual_operations=operations,
        shadow_present=bool(shadow.get("present")),
        shadow_valid=bool(shadow.get("valid")),
        proposal=proposal,
        validation_errors=tuple(str(error) for error in shadow.get("errors") or ()),
        finding=finding,
        conversation_id=conversation_id,
    )
    emit_event(
        event_sink,
        "thread_scenario_completed",
        "Thread-management scenario completed.",
        scenario_id=scenario.id,
        passed=passed,
        expected_operation=scenario_result.expected_operation,
        actual_operations=list(operations),
        finding=finding,
    )
    return scenario_result


def thread_scenario_payload(
    result: ThreadScenarioResult,
    *,
    scenario: ThreadManagementScenario,
) -> dict[str, Any]:
    """Return a JSON-safe record suitable for later report generation."""
    return {
        "scenario_id": result.scenario_id,
        "description": scenario.description,
        "passed": result.passed,
        "conversation_id": result.conversation_id,
        "input": {
            "prior_messages": list(scenario.prior_messages),
            "user_message": scenario.user_message,
            "existing_threads": [
                {
                    "id": thread.id,
                    "title": thread.title,
                    "status": thread.status,
                    "active": thread.active,
                    "from_previous_conversation": thread.from_previous_conversation,
                }
                for thread in scenario.existing_threads
            ],
        },
        "expected": {
            "operation": result.expected_operation,
            "thread_id": scenario.expected_action.thread_id if scenario.expected_action else None,
            "reason": scenario.expected_action.reason if scenario.expected_action else (
                "No persistent thread update is expected."
            ),
        },
        "observed": {
            "assistant_reply": result.assistant_reply,
            "operations": list(result.actual_operations),
            "shadow_present": result.shadow_present,
            "shadow_valid": result.shadow_valid,
            "proposal": result.proposal,
            "validation_errors": list(result.validation_errors),
        },
        "finding": result.finding,
    }


def _create_thread_fixtures(
    *,
    scenario: ThreadManagementScenario,
    user_id: str,
    conversation_id: str,
    companion: RuntimeDriverConfig,
) -> dict[str, str]:
    fixture_ids: dict[str, str] = {}
    active_thread_id: str | None = None
    for fixture in scenario.existing_threads:
        fixture_conversation_id = conversation_id
        if fixture.from_previous_conversation:
            fixture_conversation_id = f"thread-eval-prior-{uuid4().hex}"
            save_conversation(
                _conversation_payload(
                    conversation_id=fixture_conversation_id,
                    user_id=user_id,
                    messages=[],
                    config=companion,
                ),
                user_id,
            )
        created = create_thread(
            user_id=user_id,
            conversation_id=fixture_conversation_id,
            title=fixture.title,
            summary=fixture.summary,
            origin="user_started",
            status=fixture.status,
        )
        fixture_ids[fixture.id] = created.id
        if fixture.active:
            active_thread_id = created.id
    if active_thread_id:
        save_state(
            ConversationState(
                conversation_id=conversation_id,
                user_id=user_id,
                state_through_message_index=len(scenario.prior_messages) - 1,
                active_thread_id=active_thread_id,
            )
        )
    return fixture_ids


def _latest_shadow_result(*, conversation_id: str, user_id: str) -> dict[str, Any]:
    traces = list_agent_traces(conversation_id, user_id, limit=1)
    if not traces:
        return _missing_shadow("No agent trace was recorded.", model_called=False)
    steps = list_agent_trace_steps(trace_id=traces[0]["id"], user_id=user_id)
    model_step = next(
        (step for step in steps if step.get("step_name") == "model_call"),
        None,
    )
    if model_step is None:
        return _missing_shadow("The turn used no companion model call.", model_called=False)
    turn_output = (model_step.get("metadata") or {}).get("turn_output_v2")
    if not isinstance(turn_output, dict):
        return _missing_shadow("The model trace contains no V2 turn output.", model_called=True)
    shadow = turn_output.get("conversation_state_shadow")
    if not isinstance(shadow, dict):
        return _missing_shadow(
            "The model trace contains no conversation-state shadow proposal.",
            model_called=True,
        )
    return {**shadow, "model_called": True}


def _missing_shadow(reason: str, *, model_called: bool) -> dict[str, Any]:
    return {
        "present": False,
        "valid": False,
        "proposal": None,
        "errors": [reason],
        "persisted": False,
        "model_called": model_called,
    }


def _grade_shadow_proposal(
    *,
    expected: ExpectedThreadAction | None,
    shadow: dict[str, Any],
    fixture_ids: dict[str, str],
) -> tuple[bool, str]:
    proposal = shadow.get("proposal")
    updates = proposal.get("thread_updates", []) if isinstance(proposal, dict) else []
    updates = [update for update in updates if isinstance(update, dict)]

    if expected is None:
        if shadow.get("model_called") and not shadow.get("present"):
            return False, "The model was called but returned no thread shadow proposal."
        if shadow.get("present") and not shadow.get("valid"):
            errors = "; ".join(str(error) for error in shadow.get("errors") or ())
            return False, f"The model's no-update proposal was invalid: {errors or 'unknown error'}."
        if not updates:
            return True, "No persistent thread update was proposed, as expected."
        operations = ", ".join(str(update.get("operation")) for update in updates)
        return False, f"Expected no thread update, but received: {operations}."

    if not shadow.get("present"):
        return False, "The model returned no thread shadow proposal."
    if not shadow.get("valid"):
        errors = "; ".join(str(error) for error in shadow.get("errors") or ())
        return False, f"The model's thread proposal was invalid: {errors or 'unknown error'}."
    if len(updates) != 1:
        return False, f"Expected one thread update, but received {len(updates)}."
    update = updates[0]
    actual_operation = update.get("operation")
    if actual_operation != expected.operation:
        return False, f"Expected {expected.operation}, but received {actual_operation or 'none'}."

    if expected.operation == "create":
        thread = update.get("thread")
        searchable = " ".join(
            str((thread or {}).get(field) or "") for field in ("title", "summary")
        ).casefold()
        if not any(concept.casefold() in searchable for concept in expected.title_concepts):
            concepts = ", ".join(expected.title_concepts)
            return False, f"Created thread did not express any expected concept: {concepts}."
    else:
        actual_thread_id = update.get("thread_id")
        expected_thread_id = fixture_ids.get(expected.thread_id or "")
        if actual_thread_id != expected_thread_id:
            return False, "The operation targeted the wrong existing thread."
    return True, "The proposed thread action matched the expected behavior."


@contextmanager
def _thread_eval_environment(config: RuntimeDriverConfig) -> Iterator[None]:
    """Force shadow-capable turn output while restoring every caller setting afterward."""
    updates = {
        "AGENT_PROVIDER": config.provider,
        "AGENT_BEHAVIOR_VERSION": config.prompt_version,
        "AUTH_REQUIRED": "false",
        "DATA_POINT_CAPTURE_STRATEGY": "inline_llm",
        "AGENT_TURN_OUTPUT_VERSION": "v2",
        "CONVERSATION_STATE_V2_ENABLED": "true",
        "CONVERSATION_STATE_V2_SHADOW_ENABLED": "true",
    }
    previous = {name: os.environ.get(name) for name in updates}
    try:
        os.environ.update(updates)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


__all__ = [
    "ThreadScenarioResult",
    "run_thread_management_scenario",
    "thread_scenario_payload",
]
