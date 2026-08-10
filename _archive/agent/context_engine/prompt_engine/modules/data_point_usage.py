from __future__ import annotations

from agent.context_engine.models import ConversationPlan


def data_point_usage_prompt(plan: ConversationPlan) -> str:
    targets = ", ".join(plan.data_targets) if plan.data_targets else "none selected"
    return f"""Data point usage:
- Use learned data points as compact memory, not as labels to recite.
- Prefer data points over long old chat history when both say the same thing.
- If recent unextracted user messages are present, treat them as fresh evidence.
- Quietly collect useful signals only when the conversation naturally gives them.
- Do not mention internal data point categories to the user.
Useful data targets for this turn: {targets}."""
