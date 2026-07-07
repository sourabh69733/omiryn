from __future__ import annotations


def final_reminder_prompt() -> str:
    return """Final reminder:
- Use the specific context above before asking anything generic.
- Do not repeat topics listed as avoid/repeated.
- If the context is enough, make a concrete observation, playful guess, or direct answer.
- Keep it natural, brief, and human-chat-like."""
