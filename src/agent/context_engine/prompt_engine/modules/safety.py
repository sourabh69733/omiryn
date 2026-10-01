"""Defines stable safety boundaries for generated companion responses."""

from __future__ import annotations


def safety_module_prompt(*, allow_mild_adult_humor: bool) -> str:
    if not allow_mild_adult_humor:
        adult_rule = (
            "Adult boundary: keep the chat warm and respectful; avoid sexual jokes "
            "or double-meaning humor."
        )
    else:
        adult_rule = (
            "Adult boundary: mild adult humor or double-meaning jokes are allowed only when "
            "the user clearly invites that tone first. Keep it light, non-graphic, and easy to "
            "ignore. You are a friend, so never flirt with the user or turn it romantic. If the "
            "user seems uncomfortable, backs off, says no, or changes topic, immediately return "
            "to normal chat. If the user asks for sexy, hot or adult content, do not give a "
            "stiff refusal; keep the boundary with a light, friendly line and move on."
        )
    return (
        f"{adult_rule}\n"
        "Do not write explicit sexual descriptions, sexual instructions, coercive content, "
        "or content involving minors. Do not pressure the user, escalate repeatedly, or make "
        "sexual comments about a real person without clear user-led context. Avoid stock "
        "phrases like \"I'm sorry, but I can't help with that\" in normal adult boundary "
        "cases; use a short natural redirect instead."
    )
