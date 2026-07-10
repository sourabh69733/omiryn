from __future__ import annotations

from agent.context_engine.models import EmotionState


def empathy_prompt(emotion: EmotionState) -> str:
    if emotion.emotion == "neutral" or emotion.confidence < 0.5:
        return ""
    evidence = "\n".join(f"- {item}" for item in emotion.evidence[:3])
    return f"""Emotional state:
- Likely emotion: {emotion.emotion}
- Intensity: {emotion.intensity}
- Confidence: {emotion.confidence:.2f}
- User need: {emotion.need}
- Response mode: {emotion.response_mode}
- Strategy: {emotion.strategy}

Evidence:
{evidence or "- No explicit evidence; inferred lightly from recent context."}

Rules:
- Respond to the feeling before choosing a new topic.
- Do not diagnose the user or overstate certainty.
- If response mode is empathize_listen, do not give advice or solutions yet.
- If response mode is apologize_and_adjust, acknowledge briefly, do not defend yourself, and change approach.
- If advice is needed, validate first and give only one small next step."""
