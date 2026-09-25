"""Legacy deterministic understanding rules, isolated from higher-level orchestration."""

from .emotion import detect_emotion_state
from .intent import context_query_intent
from .stance import analyze_conversational_stance
from .story import continues_story

__all__ = [
    "analyze_conversational_stance",
    "context_query_intent",
    "continues_story",
    "detect_emotion_state",
]
