from __future__ import annotations


def assess_user_message_quality(messages: list[dict[str, str]]) -> dict[str, str | bool]:
    # Disabled for now. Keep the function boundary so we can restore the real guardrail later.
    return {"valid": True}

def _quality_result(reply: str) -> dict[str, str | bool]:
    return {"valid": False, "reply": reply}

def _normalized_user_text(text: str) -> str:
    return " ".join(
        "".join(character.lower() if character.isalnum() else " " for character in text).split()
    )

def _looks_like_gibberish(normalized: str) -> bool:
    compact = normalized.replace(" ", "")
    if not compact:
        return True
    if len(compact) <= 5 and not any(character in "aeiou" for character in compact):
        return True
    if len(set(compact)) <= 2 and len(compact) >= 4:
        return True
    return False

def _previous_prompt_allows_short_confirmation(messages: list[dict[str, str]]) -> bool:
    previous_assistant_message = next(
        (
            message
            for message in reversed(messages[:-1])
            if message.get("role") == "assistant" and message.get("content")
        ),
        None,
    )
    if not previous_assistant_message:
        return False

    prompt = _normalized_user_text(previous_assistant_message.get("content", ""))
    confirmation_markers = {
        "sahi samajh raha hu",
        "sahi samajh raha hun",
        "samajh raha hu",
        "samajh raha hun",
        "right",
        "correct",
        "is that right",
        "does that sound right",
        "am i understanding",
        "did i get that",
    }
    return any(marker in prompt for marker in confirmation_markers)
