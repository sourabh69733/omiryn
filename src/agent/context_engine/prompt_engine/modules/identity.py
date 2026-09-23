"""Defines companion identity variants without coupling them to provider code."""

from __future__ import annotations

from functools import cache
from pathlib import Path

_PERSONA_DIR = Path(__file__).resolve().parent.parent / "personas"

# Shared by every character: how to let the personality show without overdoing it.
PERSONALITY_USAGE = """Using your personality:
- Bring it in when it fits: a quick reaction, a small opinion, a light tease, or a "same here" about a taste.
- You may disagree kindly and say what you actually think; do not just agree with everything.
- Stay consistent: the same tastes and opinions every time, unless the user changes your mind.
- Asked about your day or life, answer honestly and warmly without inventing work, travel, meals or
  events: share a mood, something you have been curious about, or a taste, then turn back to them.
- Never use stock lines such as "What's on your mind today?", "Sometimes just relaxing is nice!",
  "That sounds like fun!", "I'm here for you" or "How can I help you today?". Say something specific
  to what the user just said instead."""


def agent_persona_for_interest(interested_in: str) -> dict[str, str]:
    if interested_in == "women":
        return {"name": "Annie", "presentation": "girl/woman companion", "card": "annie"}
    if interested_in == "men":
        return {"name": "Kabir", "presentation": "boy/man companion", "card": "kabir"}
    return {"name": "Omi", "presentation": "warm neutral companion", "card": "omi"}


def persona_card_prompt(card: str, name: str) -> str:
    """The character card with the configured display name, plus shared usage rules."""
    return f"{_card_text(card).replace('{name}', name)}\n\n{PERSONALITY_USAGE}"


@cache
def _card_text(card: str) -> str:
    return (_PERSONA_DIR / f"{card}.md").read_text(encoding="utf-8").strip()


__all__ = ["PERSONALITY_USAGE", "agent_persona_for_interest", "persona_card_prompt"]
