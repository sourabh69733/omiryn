from __future__ import annotations

from typing import Any


def style_adaptation_guide(
    profile: dict[str, Any],
    *,
    selected: bool = False,
) -> str:
    summary = profile.get("summary") or {}
    sender = str(profile.get("sender") or "selected sender")
    role = str((profile.get("metadata") or {}).get("role") or "")
    traits = _style_traits(summary)
    guidance = _style_guidance(summary)
    sample_vocabulary = _sample_vocabulary(summary)

    lines = [
        f"Style adaptation guide for {sender}{' (selected)' if selected else ''}.",
        f"Role: {role or 'unknown'}",
        f"Traits: {', '.join(traits)}",
        "How to adapt:",
        *[f"- {item}" for item in guidance],
    ]
    if sample_vocabulary:
        lines.append(f"Reusable lightweight vocabulary/topics: {', '.join(sample_vocabulary)}")
    lines.extend(
        [
            "Safety boundaries:",
            "- Match rhythm and tone, not identity.",
            "- Do not claim to be this sender.",
            "- Do not copy private sample lines verbatim unless the user explicitly asks for a quote.",
        ]
    )
    return "\n".join(lines)


def _style_traits(summary: dict[str, Any]) -> list[str]:
    traits: list[str] = []
    average_words = _float(summary.get("average_words"))
    if average_words <= 4:
        traits.append("very brief")
    elif average_words <= 8:
        traits.append("short")
    elif average_words >= 14:
        traits.append("detailed")
    else:
        traits.append("medium length")

    if _percentage(summary.get("short_message_share")) >= 60:
        traits.append("short-message heavy")
    if _percentage(summary.get("question_share")) >= 25:
        traits.append("question-led")
    if _percentage(summary.get("exclamation_share")) >= 20:
        traits.append("expressive")
    if _percentage(summary.get("emoji_like_share")) >= 20:
        traits.append("emoji/non-ASCII friendly")
    if _percentage(summary.get("lowercase_opening_share")) >= 50:
        traits.append("casual lowercase")
    return traits


def _style_guidance(summary: dict[str, Any]) -> list[str]:
    average_words = _float(summary.get("average_words"))
    question_share = _percentage(summary.get("question_share"))
    exclamation_share = _percentage(summary.get("exclamation_share"))
    lowercase_share = _percentage(summary.get("lowercase_opening_share"))
    emoji_share = _percentage(summary.get("emoji_like_share"))

    guidance: list[str] = []
    if average_words <= 4:
        guidance.append("Prefer 3-8 words when the user's message is short.")
    elif average_words <= 8:
        guidance.append("Prefer one compact sentence.")
    else:
        guidance.append("Use 1-2 natural sentences when detail is needed.")

    if question_share >= 25:
        guidance.append("A soft question is okay, but still ask at most one.")
    else:
        guidance.append("Do not force a question every reply; react naturally first.")

    if lowercase_share >= 50:
        guidance.append("Lowercase openings are acceptable in casual replies.")
    if exclamation_share < 15:
        guidance.append("Keep excitement subtle; avoid too many exclamation marks.")
    if emoji_share < 20:
        guidance.append("Avoid adding emoji unless the user uses them first.")
    else:
        guidance.append("A small emoji/non-ASCII marker is okay when it fits.")
    guidance.append("Keep the user's current language mix; Hinglish is okay when the user uses it.")
    return guidance


def _sample_vocabulary(summary: dict[str, Any]) -> list[str]:
    terms = summary.get("frequent_terms") or summary.get("topic_terms") or []
    return [str(term) for term in terms[:8] if str(term).strip()]


def _percentage(value: Any) -> float:
    text = str(value or "").strip().removesuffix("%")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
