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
    avoid_topics = "\n".join(f"- {topic}" for topic in plan.avoid_topics[:8])
    suggested_topics = "\n".join(f"- {topic}" for topic in plan.suggested_topics[:3])
    stance_context = _stance_context(plan)
    stance_rules = _stance_rules(plan)
    return f"""Conversation plan for this turn:
- Move: {plan.current_move}
- Response mode: {plan.response_mode}
- Active topic: {plan.active_topic or "none"}
- Reason: {plan.reason}
- Tone instruction: {plan.tone_instruction}
{stance_context}
{stance_rules}

Active/recent topic state:
{active_topics or "- No strong topic state yet."}

Avoid repeating these unless the user brings them back:
{avoid_topics or "- None."}

Possible fresh angles:
{suggested_topics or "- Continue the current topic with a specific observation."}

Rules:
- Do not behave like an interviewer.
- Choose emotional response mode before choosing a topic.
- If response mode is simple_ack, reply in 1-4 words and stop.
- If response mode is continue_prior_offer, continue the pending assistant offer/action.
- Prefer a playful observation, concrete recall, or specific guess before asking.
- If response mode says listen/empathize, do not jump to suggestions.
- Do not start generic music, movie, truth-or-dare, or how-was-your-day topics unless the user explicitly brings them up.
- If using music/movies, connect them to a sharper dating, memory, personality, or relationship angle.
- Ask at most one natural question, and only if it improves the flow."""


def _stance_context(plan: ConversationPlan) -> str:
    if plan.question_purpose == "optional" and plan.stance == "neutral" and not plan.user_constraints:
        return ""
    constraints = ", ".join(plan.user_constraints) or "none"
    return f"""
- Conversational stance: {plan.stance} (confidence={plan.stance_confidence:.2f})
- Claim type: {plan.claim_type}
- Question purpose: {plan.question_purpose}
- Explicit user constraints: {constraints}
- Feedback kind: {plan.feedback_kind or "none"}"""


def _stance_rules(plan: ConversationPlan) -> str:
    if plan.question_purpose == "optional" and plan.stance == "neutral" and not plan.user_constraints:
        return ""
    question_rule = {
        "none": "Do not ask a question in this reply.",
        "clarify": "You may ask one question only to clarify the user's meaning or feedback.",
        "deepen": "You may ask one specific question that deepens the active disclosure.",
        "challenge": "You may ask one question that tests the unsupported assumption without cross-examining the user.",
        "offer_choice": "You may offer one easy choice instead of an open-ended interview question.",
    }.get(plan.question_purpose, "Ask only when it has a clear conversational purpose.")
    return f"""Listener-first rules:
- Validate feelings as experiences; do not treat an unproven conclusion as fact.
- Agreement must be earned by context. Do not agree merely to soothe or please.
- Disagreement must be relevant and grounded. Do not manufacture conflict to seem human.
- Separate a valid emotional point from exaggeration or unsupported attribution.
- {question_rule}"""
