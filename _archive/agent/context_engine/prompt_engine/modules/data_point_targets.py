from __future__ import annotations


def data_point_targets_prompt(targets: tuple[str, ...]) -> str:
    if not targets:
        return ""
    return "Data point targets over time: " + ", ".join(targets) + "."
