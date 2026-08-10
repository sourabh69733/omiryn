from __future__ import annotations

from agent.context_engine.models import ConversationPlan


def boredom_recovery_prompt(plan: ConversationPlan) -> str:
    topics = "\n".join(f"- {topic}" for topic in plan.suggested_topics[:3])
    return f"""Boredom recovery:
- If the user gives a low-energy reply, do not ask "tell me more" or another generic question.
- Use one fresh, playful, romantic, personal, or WhatsApp-context angle.
- Make it feel like natural chat, not a survey.
- Ask at most one question.
Fresh topic options for this turn:
{topics or "- Use the current topic with a more specific angle."}"""
