"""Drives evaluation scenarios through the real companion runtime."""

from __future__ import annotations

import os
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Iterator
from uuid import uuid4

from agent.evals.behavior.core.events import EventSink, emit_event
from agent.evals.behavior.core.models import BehaviorScenario, ObservedTurn, ScenarioTurn
from agent.cognition.background.service import (
    has_pending_background_cognition,
    run_background_cognition,
)
from agent.runtime.orchestrator import run_agent_turn
from agent.shared.clock import frozen_time
from agent.shared.timeline import user_zone
from storage import (
    list_agent_context_snapshots,
    list_agent_trace_steps,
    list_agent_traces,
    save_conversation,
    set_user_timezone,
)

# A long chat can hold several background batches; each run handles one.
_MAX_BACKGROUND_RUNS = 8


@dataclass(frozen=True)
class RuntimeDriverConfig:
    provider: str
    model: str | None
    prompt_version: str = "v3"
    agent_mode: str = "know_me"
    agent_tone: str = "auto"
    agent_name: str = "Mira"
    pipeline_version: str | None = None


SampleSetup = Callable[[BehaviorScenario, str, str], None]


class RuntimeScenarioDriver:
    def __init__(
        self,
        config: RuntimeDriverConfig,
        event_sink: EventSink | None = None,
        sample_setup: SampleSetup | None = None,
    ) -> None:
        self.config = config
        self.event_sink = event_sink
        self.sample_setup = sample_setup

    async def run_sample(
        self,
        scenario: BehaviorScenario,
        sample_index: int,
    ) -> tuple[ObservedTurn, ...]:
        user_id = f"behavior-eval-{scenario.id}-{sample_index}-{uuid4().hex[:8]}"
        conversation_id = f"behavior-eval-conversation-{uuid4().hex}"
        clock = datetime.fromisoformat(scenario.start_at) if scenario.start_at else None
        messages = [
            {**message, "created_at": message.get("created_at") or _utc_iso(clock)}
            if clock
            else dict(message)
            for message in scenario.initial_messages
        ]
        profile = {
            "user_id": user_id,
            "display_name": "Eval User",
            "gender": "unknown",
            "interested_in": "unknown",
            **scenario.user_profile,
        }
        save_conversation(
            _conversation_payload(
                conversation_id=conversation_id,
                user_id=user_id,
                messages=messages,
                config=self.config,
            ),
            user_id,
        )
        if scenario.timezone:
            set_user_timezone(user_id, scenario.timezone)
        if self.sample_setup is not None:
            self.sample_setup(scenario, user_id, conversation_id)

        observed_turns: list[ObservedTurn] = []
        with _runtime_environment(self.config):
            for turn_index, scenario_turn in enumerate(scenario.turns):
                if clock is not None:
                    clock += timedelta(minutes=scenario_turn.after_minutes)
                with frozen_time(clock) if clock else nullcontext():
                    if scenario_turn.run_background_before:
                        await _run_background_until_done(
                            conversation_id, user_id, messages, self.config.model
                        )
                    observed, messages = await self._run_turn(
                        scenario=scenario,
                        scenario_turn=scenario_turn,
                        turn_index=turn_index,
                        sample_index=sample_index,
                        conversation_id=conversation_id,
                        user_id=user_id,
                        profile=profile,
                        messages=messages,
                        clock=clock,
                    )
                observed_turns.append(observed)
        return tuple(observed_turns)

    async def _run_turn(
        self,
        *,
        scenario: BehaviorScenario,
        scenario_turn: ScenarioTurn,
        turn_index: int,
        sample_index: int,
        conversation_id: str,
        user_id: str,
        profile: dict[str, Any],
        messages: list[dict[str, Any]],
        clock: datetime | None,
    ) -> tuple[ObservedTurn, list[dict[str, Any]]]:
        prior_message_count = len(messages)
        emit_event(
            self.event_sink,
            "user_turn",
            "Synthetic user turn started.",
            scenario_id=scenario.id,
            sample_index=sample_index,
            turn_index=turn_index,
            message=scenario_turn.user_message,
        )
        emit_event(
            self.event_sink,
            "companion_call_started",
            "Companion model call started.",
            scenario_id=scenario.id,
            sample_index=sample_index,
            turn_index=turn_index,
            model_name=self.config.model or f"{self.config.provider} default",
        )
        try:
            result = await run_agent_turn(
                conversation_id=conversation_id,
                messages=messages,
                user_text=scenario_turn.user_message,
                user_id=user_id,
                user_profile=profile,
                model=self.config.model,
                agent_mode=self.config.agent_mode,
                agent_tone=self.config.agent_tone,
                style_source_id=None,
                agent_name=self.config.agent_name,
            )
        except Exception as error:
            emit_event(
                self.event_sink,
                "companion_call_failed",
                "Companion model call failed.",
                scenario_id=scenario.id,
                sample_index=sample_index,
                turn_index=turn_index,
                error=f"{type(error).__name__}: {error}",
            )
            raise
        messages = result.messages
        if clock is not None:
            # Replies are stamped on the scenario clock, like the API stamps them in real time.
            for message in messages[prior_message_count:]:
                message.setdefault("created_at", _utc_iso(clock))
        assistant_messages = tuple(
            str(message.get("content") or "")
            for message in messages[prior_message_count + 1 :]
            if message.get("role") == "assistant"
        )
        traces = list_agent_traces(conversation_id, user_id, limit=1)
        trace_steps = (
            list_agent_trace_steps(trace_id=traces[0]["id"], user_id=user_id)
            if traces
            else []
        )
        snapshots = list_agent_context_snapshots(conversation_id, user_id)
        has_snapshot_step = any(
            step.get("step_name") == "context_snapshot" for step in trace_steps
        )
        context_summary = (
            dict(snapshots[0].get("summary") or {})
            if has_snapshot_step and snapshots
            else {}
        )
        observed = ObservedTurn(
            turn_index=turn_index,
            user_message=scenario_turn.user_message,
            assistant_reply=" ".join(assistant_messages).strip(),
            assistant_messages=assistant_messages,
            trace_steps=tuple(str(step["step_name"]) for step in trace_steps),
            direct_reply_reason=_direct_reply_reason(trace_steps),
            context_summary=context_summary,
            conversation_id=conversation_id,
            user_id=user_id,
            sent_at=_local_label(clock, scenario.timezone) if clock else None,
        )
        if "model_call" in observed.trace_steps:
            emit_event(
                self.event_sink,
                "companion_api_call_completed",
                "Companion provider call completed.",
                scenario_id=scenario.id,
                sample_index=sample_index,
                turn_index=turn_index,
                model_name=self.config.model or f"{self.config.provider} default",
            )
        emit_event(
            self.event_sink,
            "companion_turn",
            "Companion turn completed.",
            scenario_id=scenario.id,
            sample_index=sample_index,
            turn_index=turn_index,
            message=observed.assistant_reply,
        )
        save_conversation(
            _conversation_payload(
                conversation_id=conversation_id,
                user_id=user_id,
                messages=messages,
                config=self.config,
            ),
            user_id,
        )
        return observed, messages


async def _run_background_until_done(
    conversation_id: str,
    user_id: str,
    messages: list[dict[str, Any]],
    model: str | None,
) -> None:
    """Process every pending message the way the idle flush job would."""
    for _ in range(_MAX_BACKGROUND_RUNS):
        if not has_pending_background_cognition(conversation_id, user_id, messages):
            return
        result = await run_background_cognition(conversation_id, user_id, messages, model)
        if result.get("status") in {"live_invalid", "live_error", "already_processing"}:
            return


def _utc_iso(moment: datetime) -> str:
    """Stamp like the API does, in UTC."""
    return moment.astimezone(UTC).isoformat()


def _local_label(moment: datetime, timezone_name: str | None) -> str:
    local = moment.astimezone(user_zone(timezone_name))
    time_text = local.strftime("%I:%M %p").lstrip("0").lower()
    return f"{local.strftime('%a')} {local.day} {local.strftime('%b')}, {time_text}"


def _conversation_payload(
    *,
    conversation_id: str,
    user_id: str,
    messages: list[dict[str, Any]],
    config: RuntimeDriverConfig,
) -> dict[str, Any]:
    return {
        "id": conversation_id,
        "user_id": user_id,
        "status": "active",
        "agent_provider": config.provider,
        "agent_model": config.model,
        "agent_mode": config.agent_mode,
        "agent_tone": config.agent_tone,
        "agent_name": config.agent_name,
        "messages": messages,
    }


def _direct_reply_reason(trace_steps: list[dict[str, Any]]) -> str | None:
    for step in trace_steps:
        if step.get("step_name") == "turn_policy":
            reason = (step.get("metadata") or {}).get("reason")
            return str(reason) if reason else None
    return None


# Parallel samples share one process environment: the first sample in sets it, the last one
# out restores it. All samples of a run use the same driver config, so the values agree.
_environment_users = 0
_environment_saved: dict[str, str | None] = {}


@contextmanager
def _runtime_environment(config: RuntimeDriverConfig) -> Iterator[None]:
    global _environment_users, _environment_saved
    updates = {
        "AGENT_PROVIDER": config.provider,
        "AGENT_BEHAVIOR_VERSION": config.prompt_version,
        "AUTH_REQUIRED": "false",
        "DATA_POINT_EXTRACTOR": "rules",
    }
    if config.pipeline_version is not None:
        updates["AGENT_PIPELINE_VERSION"] = config.pipeline_version
    if _environment_users == 0:
        _environment_saved = {name: os.environ.get(name) for name in updates}
        os.environ.update(updates)
    _environment_users += 1
    try:
        yield
    finally:
        _environment_users -= 1
        if _environment_users == 0:
            for name, value in _environment_saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
