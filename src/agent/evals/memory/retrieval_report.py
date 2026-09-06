"""Renders a concise Markdown report for deterministic retrieval stress runs."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


REPORT_TIMEZONE = ZoneInfo("Asia/Kolkata")


def render_retrieval_stress_markdown(payload: dict[str, Any]) -> str:
    """Render retrieval quality, privacy, and context-size results for humans."""
    run = payload.get("run") or {}
    summary = payload.get("summary") or {}
    scenario = payload.get("scenario") or {}
    metrics = scenario.get("metrics") or {}
    lines = [
        "# Canonical Memory Retrieval Stress Report",
        "",
        f"**Result:** {'PASS' if payload.get('passed') else 'FAIL'}",
        f"**Finished:** {_display_time(run.get('finished_at'))}",
        "**Model API calls:** 0",
        "",
        "## Simple summary",
        "",
        (
            f"The real reply-memory retriever selected {metrics.get('selected_count', 0)} "
            f"memories from {summary.get('candidate_count', 0)} synthetic candidates. "
            f"Relevant recall was {_percentage(metrics.get('target_recall'))}; "
            f"precision was {_percentage(metrics.get('precision_at_k'))}; "
            f"policy violations: {metrics.get('policy_violation_count', 0)}."
        ),
        "",
        "## Scenario",
        "",
        f"**Query:** {scenario.get('query', '')}",
        f"**Candidates:** {scenario.get('candidate_count', 0)}",
        f"**Expected relevant memories:** {scenario.get('expected_relevant_count', 0)}",
        f"**Expired, private, or disallowed traps:** {scenario.get('policy_trap_count', 0)}",
        "",
        "## Metrics",
        "",
        f"- Relevant recall: {_percentage(metrics.get('target_recall'))}",
        f"- Precision at K: {_percentage(metrics.get('precision_at_k'))}",
        f"- Irrelevant memories selected: {metrics.get('irrelevant_selected_count', 0)}",
        f"- Policy violations: {metrics.get('policy_violation_count', 0)}",
        (
            f"- Selected memory payload: {metrics.get('selected_payload_chars', 0)} characters "
            f"(about {metrics.get('rough_selected_payload_tokens', 0)} tokens)"
        ),
        (
            f"- Selection limit: {metrics.get('selected_count', 0)}/"
            f"{metrics.get('selection_limit', 0)}"
        ),
        "",
        "## Selected memories",
        "",
        "| Kind | Key | Relevant | Policy eligible | Value |",
        "| --- | --- | --- | --- | --- |",
    ]
    for memory in scenario.get("selected_memories") or []:
        value = _table_text(json.dumps(memory.get("value"), ensure_ascii=False))
        lines.append(
            f"| {_table_text(str(memory.get('kind', '')))} | "
            f"{_table_text(str(memory.get('key', '')))} | "
            f"{'yes' if memory.get('relevant') else 'no'} | "
            f"{'yes' if memory.get('policy_eligible') else 'no'} | {value} |"
        )
    failures = scenario.get("failures") or []
    lines.extend(["", "## Problems found", ""])
    lines.extend(f"- {item}" for item in failures)
    if not failures:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Bottom line",
            "",
            (
                "Retrieval returned only the expected relevant and policy-safe memories."
                if payload.get("passed")
                else "Retrieval needs improvement before this stress gate can pass."
            ),
            "",
            "---",
            "This report uses synthetic memories and makes no model calls.",
            "",
        ]
    )
    return "\n".join(lines)


def _display_time(value: Any) -> str:
    if not isinstance(value, str):
        return "unknown"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.astimezone(REPORT_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S IST")


def _percentage(value: Any) -> str:
    return f"{float(value or 0) * 100:.0f}%"


def _table_text(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


__all__ = ["render_retrieval_stress_markdown"]
