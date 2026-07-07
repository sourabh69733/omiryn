from __future__ import annotations

from agent.context_engine.prompt_engine.models import PromptBehaviorVersion
from agent.context_engine.models import ConversationPlan, TopicState


def conversation_flow_prompt(prompt_version: PromptBehaviorVersion) -> str:
    flow = prompt_version.conversation_flow
    if not flow:
        return ""
    return (
        "Conversation flow config: "
        f"dry_reply_strategy={flow.get('dry_reply_strategy')}; "
        f"starter_strategy={flow.get('starter_strategy')}; "
        f"allow_imagined_scenes={flow.get('allow_imagined_scenes')}; "
        f"emotional_depth={flow.get('emotional_depth')}."
    )


def conversation_plan_prompt(
    plan: ConversationPlan,
    topic_states: list[TopicState],
) -> str:
    active_topics = "\n".join(
        f"- {state.label} | status={state.status}; depth={state.depth}; repeats={state.repeat_count}"
        for state in topic_states[:5]
    )
    avoid_topics = "\n".join(f"- {topic}" for topic in plan.avoid_topics[:4])
    suggested_topics = "\n".join(f"- {topic}" for topic in plan.suggested_topics[:3])
    return f"""Conversation plan for this turn:
- Move: {plan.current_move}
- Active topic: {plan.active_topic or "none"}
- Reason: {plan.reason}
- Tone instruction: {plan.tone_instruction}

Active/recent topic state:
{active_topics or "- No strong topic state yet."}

Avoid repeating these unless the user brings them back:
{avoid_topics or "- None."}

Possible fresh angles:
{suggested_topics or "- Continue the current topic with a specific observation."}

Rules:
- Do not behave like an interviewer.
- Prefer a playful observation, concrete recall, or specific guess before asking.
- Ask at most one natural question, and only if it improves the flow."""
