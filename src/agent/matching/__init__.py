"""Matching: is a user known well enough to match, and how two users would get along.

Code computes the facts (which vibe areas have proof, which meet facts are known, which areas two
cards share); a model writes the reasons; code checks every reason against the cards.
"""

from .compatibility import MatchCheck, check_compatibility, comparable_areas, compatibility_score, validate_match_reasons
from .pool import pool_view, propose_pair
from .readiness import MEET_FACTS, MatchReadiness, match_readiness, readiness_from

__all__ = [
    "MEET_FACTS",
    "MatchCheck",
    "MatchReadiness",
    "check_compatibility",
    "comparable_areas",
    "compatibility_score",
    "match_readiness",
    "pool_view",
    "propose_pair",
    "readiness_from",
    "validate_match_reasons",
]
