"""Translates the conversation plan into model-facing flow instructions."""

from __future__ import annotations

from agent.context_engine.prompt_engine.models import PromptBehaviorVersion
from agent.context_engine.contracts.models import ConversationPlan


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


def conversation_plan_prompt(plan: ConversationPlan) -> str:
    avoid_topics = "\n".join(f"- {topic}" for topic in plan.avoid_topics[:8])
    suggested_topics = "\n".join(f"- {topic}" for topic in plan.suggested_topics[:3])
    stance_context = _stance_context(plan)
    stance_rules = _stance_rules(plan)
    thread_context = _thread_context(plan)
    return f"""Conversation plan for this turn:
- Move: {plan.current_move}
- Response mode: {plan.response_mode}
- Active topic: {plan.active_topic or "none"}
- Reason: {plan.reason}
- Tone instruction: {plan.tone_instruction}
{stance_context}
{stance_rules}
{thread_context}

Avoid repeating these unless the user brings them back:
{avoid_topics or "- None."}

Possible fresh angles:
{suggested_topics or "- Continue the current subject with a specific observation."}

Rules:
- If the user asked something, or seems confused by your last reply, answer that first in plain
  words. Do not move to another subject until they are with you.
- Do not behave like an interviewer.
- Choose emotional response mode before choosing a topic.
- If response mode is simple_ack, reply in 1-4 words and stop.
- If response mode is continue_prior_offer, continue the pending assistant offer/action.
- Prefer a playful observation, concrete recall, or specific guess before asking.
- If response mode says listen/empathize, do not jump to suggestions.
- Do not start generic music, movie, truth-or-dare, or how-was-your-day topics unless the user explicitly brings them up.
- If using music/movies, connect them to a sharper memory, personality, or opinion angle.
- Ask at most one natural question, and only if it improves the flow."""


def _thread_context(plan: ConversationPlan) -> str:
    if plan.thread_action == "none":
        return ""
    subject = plan.thread_title or "none"
    next_angle = plan.thread_next_angle or "none"
    instruction = {
        "follow_user": "Follow the current user message; do not steer back to a tracked subject.",
        "continue_active": "Continue this active subject naturally without repeating its summary or interviewing the user.",
        "offer_open": "Offer this unfinished subject lightly; make it easy for the user to decline.",
        "ignore_unengaged": "Do not revive this subject; the user has not shown interest in it.",
    }.get(plan.thread_action, "Do not force a tracked subject into the reply.")
    return f"""Thread continuity decision:
- Action: {plan.thread_action}
- Subject: {subject}
- Possible next angle: {next_angle}
- {instruction}
- Never mention thread tracking, IDs, actions, or internal state."""


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
