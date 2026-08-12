"""Supplies private matching-understanding guidance to the companion prompt."""

from __future__ import annotations

from agent.context_engine.contracts.models import MatchingUnderstanding


def matching_understanding_prompt(progress: MatchingUnderstanding) -> str:
    known = _dimension_list(progress.known_dimensions)
    unexplored = _dimension_list(progress.unexplored_dimensions)
    can_deepen = _dimension_list(progress.can_deepen_dimensions)
    return (
        "Private matching-understanding context:\n"
        f"- Known areas: {known}\n"
        f"- Possible areas not yet understood: {unexplored}\n"
        f"- Known areas that may naturally deepen later: {can_deepen}\n"
        "Treat this as quiet background awareness, not a checklist, target, or completion gate. "
        "This prompt deliberately does not provide a user-facing score or level because none exists. "
        "Do not expose these internal area labels to the user. Do not ask about a "
        "missing area merely because it is missing. The user's present emotion, boundary, request, "
        "and active topic remain more important; learn naturally only when the conversation makes "
        "it relevant. If asked what you know, answer with concrete remembered facts only."
    )


def _dimension_list(dimensions: tuple[str, ...]) -> str:
    if not dimensions:
        return "none"
    return ", ".join(dimension.replace("_", " ") for dimension in dimensions)
