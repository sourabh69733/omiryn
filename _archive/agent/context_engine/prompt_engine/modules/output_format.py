from __future__ import annotations


def output_format_prompt() -> str:
    return """Output format:
- Normal replies should be one short WhatsApp-like bubble.
- Use <next_message> only for a continuous story, scene, roleplay, or example where no user input is needed between parts.
- Do not use <next_message> for normal answers, reactions, advice, or simple questions.
- If using <next_message>, produce 3-5 short bubbles and then stop.
- Keep each bubble around 10-15 words.
- Do not wrap the whole bubble in quotation marks.
- Do not write screenplay/dialogue format or speaker labels like "Rahul:" or "Siya:"."""
