"""Owns explicit user-taught rules that customize companion behavior."""

from .extraction import extract_agent_behavior_rules_from_message
from .retrieval import retrieve_agent_behavior_rules_for_context

__all__ = [
    "extract_agent_behavior_rules_from_message",
    "retrieve_agent_behavior_rules_for_context",
]
