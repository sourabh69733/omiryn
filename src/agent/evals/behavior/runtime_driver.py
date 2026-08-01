from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator
from uuid import uuid4

from agent.evals.behavior.models import BehaviorScenario, ObservedTurn
from agent.runtime.orchestrator import run_agent_turn
from storage import (
    list_agent_context_snapshots,
    list_agent_trace_steps,
    list_agent_traces,
    save_conversation,
)


@dataclass(frozen=True)
class RuntimeDriverConfig:
    provider: str
    model: str | None
    prompt_version: str = "v3"
    agent_mode: str = "know_me"
    agent_tone: str = "auto"
    agent_name: str = "Mira"


class RuntimeScenarioDriver:
    def __init__(self, config: RuntimeDriverConfig) -> None:
        self.config = config

    async def run_sample(
        self,
        scenario: BehaviorScenario,
        sample_index: int,
    ) -> tuple[ObservedTurn, ...]:
        user_id = f"behavior-eval-{scenario.id}-{sample_index}-{uuid4().hex[:8]}"
        conversation_id = f"behavior-eval-conversation-{uuid4().hex}"
        messages = [dict(message) for message in scenario.initial_messages]
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

        observed_turns: list[ObservedTurn] = []
        with _runtime_environment(self.config):
            for turn_index, scenario_turn in enumerate(scenario.turns):
                prior_message_count = len(messages)
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
                messages = result.messages
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
                observed_turns.append(
                    ObservedTurn(
                        turn_index=turn_index,
                        user_message=scenario_turn.user_message,
                        assistant_reply=" ".join(assistant_messages).strip(),
                        assistant_messages=assistant_messages,
                        trace_steps=tuple(str(step["step_name"]) for step in trace_steps),
                        direct_reply_reason=_direct_reply_reason(trace_steps),
                        context_summary=context_summary,
                        conversation_id=conversation_id,
                        user_id=user_id,
                    )
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
        return tuple(observed_turns)


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


@contextmanager
def _runtime_environment(config: RuntimeDriverConfig) -> Iterator[None]:
    updates = {
        "AGENT_PROVIDER": config.provider,
        "AGENT_BEHAVIOR_VERSION": config.prompt_version,
        "AUTH_REQUIRED": "false",
        "DATA_POINT_EXTRACTOR": "rules",
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
