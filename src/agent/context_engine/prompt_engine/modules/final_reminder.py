from __future__ import annotations

from agent.context_engine.models import ConversationPlan


def final_reminder_prompt(plan: ConversationPlan | None = None) -> str:
    reminder = """Final reminder:
- If Conversation Plan response mode is simple_ack, reply with only a tiny acknowledgement and stop.
- Use the specific context above before asking anything generic.
- Do not repeat topics listed as avoid/repeated.
- If the context is enough, make a concrete observation, playful guess, or direct answer.
- Keep it natural, brief, and human-chat-like."""
    if not plan or plan.question_purpose == "optional":
        return reminder
    question_rule = {
        "none": "Do not ask a question in this reply.",
        "clarify": "Ask at most one question, only if clarification is truly necessary.",
        "deepen": "Ask at most one specific question that deepens the active disclosure.",
        "challenge": "Ask at most one question that gently tests the unsupported assumption.",
        "offer_choice": "Offer one easy choice instead of an open-ended question.",
    }.get(plan.question_purpose, "Ask only when it has a clear conversational purpose.")
    constraint_rule = (
        f"- Hard user constraints: {', '.join(plan.user_constraints)}.\n"
        if plan.user_constraints
        else ""
    )
    return (
        f"{reminder}\n"
        "- Follow the decided conversational stance and explicit user constraints before all topic suggestions.\n"
        f"{constraint_rule}"
        f"- Question purpose for this reply: {plan.question_purpose}. {question_rule}"
    )
