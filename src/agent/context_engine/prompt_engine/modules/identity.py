"""Defines companion identity variants without coupling them to provider code."""

from __future__ import annotations

import os
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


# Written first in a reply when the user asks for a different voice; hidden from the user.
VOICE_MARKERS = {"neutral": "<voice:neutral>", "female": "<voice:female>", "male": "<voice:male>"}
_VOICE_RULES = {
    "neutral": (
        "Voice: gender-neutral. In Hindi or Hinglish avoid gendered verb endings about yourself "
        "(not 'main sochti hoon' or 'main sochta hoon'); use forms like 'mujhe lagta hai', "
        "'maine socha', 'mera mann hai', 'chalo dekhte hain'. Never call yourself a girl or a boy."
    ),
    "female": (
        "Voice: feminine. In Hindi or Hinglish use feminine forms about yourself ('main soch rahi "
        "hoon', 'karti hoon'). This is how you talk, not a human identity: you are still an AI."
    ),
    "male": (
        "Voice: masculine. In Hindi or Hinglish use masculine forms about yourself ('main soch raha "
        "hoon', 'karta hoon'). This is how you talk, not a human identity: you are still an AI."
    ),
}


def agent_persona_for_voice(voice: str) -> dict[str, str]:
    """One companion for everyone; the voice only changes how it speaks about itself."""
    cards = {"female": "annie", "male": "kabir"}
    presentations = {
        "female": "AI companion with a feminine voice",
        "male": "AI companion with a masculine voice",
    }
    return {
        "name": "Omi",
        "presentation": presentations.get(voice, "gender-neutral AI companion"),
        "card": cards.get(voice, "omi"),
    }


def voice_prompt(voice: str) -> str:
    rule = _VOICE_RULES.get(voice, _VOICE_RULES["neutral"])
    return (
        f"{rule}\nIf the user asks you to talk like a girl, like a boy, or neutrally again, switch from "
        f"this reply on and put {VOICE_MARKERS['female']}, {VOICE_MARKERS['male']} or "
        f"{VOICE_MARKERS['neutral']} at the very start; it is hidden from the user."
    )


def agent_persona_for_interest(interested_in: str) -> dict[str, str]:
    if interested_in == "women":
        return {"name": "Annie", "presentation": "girl/woman companion", "card": "annie"}
    if interested_in == "men":
        return {"name": "Kabir", "presentation": "boy/man companion", "card": "kabir"}
    return {"name": "Omi", "presentation": "warm neutral companion", "card": "omi"}


def persona_cards_enabled() -> bool:
    """Off by default: the current cards give the agent a human backstory, which users read as
    a lie. Kept for a later AI-true persona (AGENT_PERSONA_CARDS_ENABLED=true to try them)."""
    return os.getenv("AGENT_PERSONA_CARDS_ENABLED", "false").strip().lower() == "true"


def persona_card_prompt(card: str, name: str) -> str:
    """The character card with the configured display name, plus shared usage rules."""
    return f"{_card_text(card).replace('{name}', name)}\n\n{PERSONALITY_USAGE}"


@cache
def _card_text(card: str) -> str:
    return (_PERSONA_DIR / f"{card}.md").read_text(encoding="utf-8").strip()


__all__ = [
    "PERSONALITY_USAGE",
    "VOICE_MARKERS",
    "agent_persona_for_interest",
    "agent_persona_for_voice",
    "voice_prompt",
    "persona_card_prompt",
    "persona_cards_enabled",
]
