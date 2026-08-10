from __future__ import annotations

from agent.context_engine.contracts.models import MatchingUnderstanding


def matching_understanding_prompt(progress: MatchingUnderstanding) -> str:
    known = _dimension_list(progress.known_dimensions)
    unexplored = _dimension_list(progress.unexplored_dimensions)
    can_deepen = _dimension_list(progress.can_deepen_dimensions)
    return (
        "Private matching-understanding context:\n"
        f"- Current understanding level: {progress.level}\n"
        f"- Foundation understood: {progress.foundation_covered} of {progress.foundation_total}\n"
        f"- Known areas: {known}\n"
        f"- Not yet understood: {unexplored}\n"
        f"- Areas that could be understood more deeply: {can_deepen}\n"
        "Treat this as quiet background awareness, not a checklist, target, or completion gate. "
        "Do not expose these internal labels or the progress level to the user. Do not ask about a "
        "missing area merely because it is missing. The user's present emotion, boundary, request, "
        "and active topic remain more important; learn naturally only when the conversation makes "
        "it relevant."
    )


def _dimension_list(dimensions: tuple[str, ...]) -> str:
    if not dimensions:
        return "none"
    return ", ".join(dimension.replace("_", " ") for dimension in dimensions)
