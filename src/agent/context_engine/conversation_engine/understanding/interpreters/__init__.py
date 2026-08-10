"""Versioned strategies that combine language, intent, emotion, and stance signals."""

from .legacy_en_hi import LegacyEnglishHindiInterpreter
from .registry import interpret_turn

__all__ = ["LegacyEnglishHindiInterpreter", "interpret_turn"]
