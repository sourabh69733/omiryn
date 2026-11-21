"""The ability run as a page a person can read: the score by stage, area and need, then every reply."""

from __future__ import annotations

from collections import Counter

from agent.evals.abilities.questions import AREAS, NEEDS, WHO
from agent.evals.abilities.runner import REASONS, Asked, Mark

Result = tuple[Asked, Mark]


def tally(results: list[Result]) -> Counter:
    """right / partly / wrong, and not_run for what the test cannot send."""
    return Counter("not_run" if mark.reason == "not_run" and not asked.reply and not asked.error else mark.verdict for asked, mark in results)


def _score_rows(results: list[Result], key, labels: dict[str, str]) -> list[str]:
    rows = []
    for name, label in labels.items():
        group = [result for result in results if key(result[0].question) == name]
        if not group:
            continue
        counts = tally(group)
        rows.append(f"| {label} | {counts['right']} | {counts['partly']} | {counts['wrong']} | {counts['right'] + counts['partly'] + counts['wrong']} |")
    return rows


def _table(title: str, rows: list[str]) -> list[str]:
    if not rows:
        return []
    return [f"### {title}", "", f"| {title} | Right | Partly | Wrong | Asked |", "|---|---|---|---|---|", *rows, ""]


def _looked_up(asked: Asked) -> str:
    if not asked.tools:
        return "nothing"
    return "; ".join(f"{tool.name}({', '.join(f'{k}={v!r}' for k, v in tool.arguments.items())}) gave {len(tool.returned)} letters" for tool in asked.tools)


def as_markdown(results: list[Result], *, reply_model: str, judge_model: str, when: str, cost_usd: float | None = None) -> str:
    counts = tally(results)
    marked = counts["right"] + counts["partly"] + counts["wrong"]
    career = [result for result in results if result[0].question.area == "career"]
    lines = [
        "# Ability run",
        "",
        f"Reply model `{reply_model}` · judge `{judge_model}` · {when}",
        "",
        f"**{counts['right']} right, {counts['partly']} partly, {counts['wrong']} wrong** out of {marked} asked."
        + (f" {counts['not_run']} could not be sent." if counts["not_run"] else "")
        + (f" Cost of this run: ${cost_usd:.2f}." if cost_usd is not None else ""),
        "",
        "The marks are by a judge model reading each reply against the written rule. Every reply is below; overrule any mark you disagree with.",
        "",
        "## Score",
        "",
        *_table("Career, by who asks", _score_rows(career, lambda q: q.who, WHO)),
        *_table("Area", _score_rows(results, lambda q: q.area, AREAS)),
        *_table("What Omi had to do", _score_rows(results, lambda q: q.needs, NEEDS)),
        "## Why replies were not right",
        "",
        "| Reason | Replies |",
        "|---|---|",
        *(
            f"| {REASONS[reason]} | {count} |"
            for reason, count in Counter(mark.reason for _, mark in results if mark.verdict != "right").most_common()
        ),
        "",
        "## Every question",
        "",
    ]
    for area, title in AREAS.items():
        group = [result for result in results if result[0].question.area == area]
        if not group:
            continue
        lines += [f"### {title}", ""]
        for asked, mark in group:
            question = asked.question
            lines.append(f"**{question.id}** · {mark.verdict.upper()} · {REASONS[mark.reason]}")
            if question.earlier:
                lines.append(f"- Said earlier: {question.earlier}")
            lines += [
                f"- Asked ({WHO[question.who].split(',')[0].split('(')[0].strip()}): {question.text}",
                f"- Right when: {question.right_when}",
                f"- Looked up: {_looked_up(asked)}",
                "- Omi: " + (asked.reply.replace("\n", " / ") if asked.reply else f"(nothing) {asked.error}"),
                f"- Mark ({mark.by}, {asked.seconds:.0f}s): {mark.note}",
                "",
            ]
    return "\n".join(lines)


__all__ = ["as_markdown", "tally"]
