"""Writes Markdown, JSON, and historical evaluation summaries."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from agent.evals.behavior.reporting.live import LiveRunStats

REPORT_TIMEZONE = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class SavedReportPaths:
    markdown: Path
    json: Path
    history: Path


def attach_run_metadata(
    payload: dict[str, Any],
    *,
    stats: LiveRunStats,
    companion_provider: str,
    companion_model: str,
    prompt_version: str,
    companion_agent_name: str = "Mira",
) -> None:
    payload["run"] = {
        "started_at": stats.started_at.isoformat(),
        "finished_at": stats.finished_at.isoformat(),
        "duration_seconds": stats.duration_seconds,
        "api_calls": stats.api_calls,
    }
    payload["companion"] = {
        "agent_name": companion_agent_name,
        "provider": companion_provider,
        "model": companion_model,
        "prompt_version": prompt_version,
    }


def save_evaluation_reports(
    payload: dict[str, Any],
    *,
    output_dir: Path,
    explicit_json_path: Path | None = None,
    now: datetime | None = None,
) -> SavedReportPaths:
    timestamp = now or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    if explicit_json_path is not None:
        json_path = explicit_json_path
        if not json_path.is_absolute():
            json_path = Path.cwd() / json_path
        markdown_path = json_path.with_suffix(".md")
        json_path.parent.mkdir(parents=True, exist_ok=True)
        history_path = output_dir / "HISTORY.md"
    else:
        stem = _report_stem(payload, timestamp)
        day_directory = output_dir / _history_day(timestamp)
        day_directory.mkdir(parents=True, exist_ok=True)
        json_path = day_directory / f"{stem}.json"
        markdown_path = day_directory / f"{stem}.md"
        history_path = output_dir / "HISTORY.md"

    payload["report_files"] = {
        "markdown": str(markdown_path.resolve()),
        "json": str(json_path.resolve()),
        "history": str(history_path.resolve()),
    }
    _write_text_atomic(markdown_path, render_markdown_report(payload))
    _write_text_atomic(
        json_path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    _append_history(history_path, payload, timestamp)
    return SavedReportPaths(
        markdown=markdown_path,
        json=json_path,
        history=history_path,
    )


def render_markdown_report(payload: dict[str, Any]) -> str:
    if payload.get("stage") == "memory_retrieval_stress_eval":
        from agent.evals.memory.retrieval_report import render_retrieval_stress_markdown

        return render_retrieval_stress_markdown(payload)
    if payload.get("stage") == "memory_retrieval_cases_eval":
        from agent.evals.memory.retrieval_report import render_retrieval_cases_markdown

        return render_retrieval_cases_markdown(payload)
    result = _result_label(payload)
    run = payload.get("run") or {}
    companion = payload.get("companion") or {}
    calibration = payload.get("judge_calibration") or {}
    is_memory_eval = payload.get("stage") in {
        "memory_shadow_eval",
        "memory_v3_eval",
        "memory_judge_calibration",
    }
    lines = [
        (
            "# Canonical V3 Memory Evaluation Report"
            if payload.get("stage") == "memory_v3_eval"
            else "# Background Memory Evaluation Report"
        )
        if is_memory_eval
        else "# Companion Evaluation Report",
        "",
        f"**Result:** {result}",
        f"**Finished:** {_display_time(run.get('finished_at'))}",
        (
            f"**Memory extractor:** {companion.get('agent_name', 'unknown')}"
            if is_memory_eval
            else f"**Companion agent:** {companion.get('agent_name', 'unknown')}"
        ),
        (
            f"**Extractor provider:** {companion.get('provider', 'unknown')}"
            if is_memory_eval
            else f"**Companion provider:** {companion.get('provider', 'unknown')}"
        ),
        (
            f"**Extractor model:** {companion.get('model', 'provider-default')}"
            if is_memory_eval
            else f"**Companion model:** {companion.get('model', 'provider-default')}"
        ),
        f"**Prompt version:** {companion.get('prompt_version', 'unknown')}",
        f"**Judges:** {', '.join(payload.get('judges') or ['not run'])}",
        f"**Duration:** {run.get('duration_seconds', 0):.1f} seconds",
        f"**Model API calls:** {run.get('api_calls', 0)}",
        "",
        "## Simple summary",
        "",
        _simple_summary(payload),
        "",
    ]
    if payload.get("stage") == "simulated_conversation":
        lines.extend(_simulated_conversations_markdown(payload))
    elif payload.get("stage") == "simulated_conversation_suite":
        lines.extend(_simulated_conversation_suite_markdown(payload))
    elif payload.get("stage") == "conversation_judge_calibration":
        lines.extend(_conversation_judge_calibration_markdown(payload))
    elif payload.get("stage") == "thread_management_shadow_eval":
        lines.extend(_thread_management_shadow_markdown(payload))
    elif payload.get("stage") in {"memory_shadow_eval", "memory_v3_eval"}:
        lines.extend(_memory_shadow_markdown(payload))
    elif payload.get("stage") == "memory_judge_calibration":
        lines.extend(_memory_judge_calibration_markdown(calibration))
    else:
        lines.extend(
            [
                "## Judge reliability check",
                "",
                (
                    f"The judges completed {calibration.get('completed_cases', 0)}/"
                    f"{calibration.get('total_cases', 0)} known examples. "
                    f"Errors: {calibration.get('judge_errors', 0)}. "
                    f"Result: {'PASS' if calibration.get('passed') else 'FAIL'}."
                ),
            ]
        )
    failed_calibration_cases = [
        case for case in calibration.get("cases", []) if not case.get("passed")
    ]
    if failed_calibration_cases:
        lines.extend(["", "### Problems found"])
        for case in failed_calibration_cases:
            reason = (
                case.get("judge_error")
                or case.get("failure_reason")
                or _calibration_failure_reason(case)
            )
            lines.append(f"- **{_plain_name(case['id'])}:** {reason}")

    if payload.get("stage") == "behavior_evaluation":
        for scenario in payload.get("scenarios", []):
            lines.extend(_scenario_markdown(scenario))

    if payload.get("stage") in {"simulated_conversation", "simulated_conversation_suite"}:
        lines.extend(_improvement_targets_markdown(payload))
        lines.extend(_human_review_markdown(payload))

    lines.extend(
        [
            "",
            "## Bottom line",
            "",
            _bottom_line(payload),
            "",
            "---",
            "This report contains synthetic evaluation conversations, not production user chats.",
            "",
        ]
    )
    return "\n".join(lines)


def _scenario_markdown(scenario: dict[str, Any]) -> list[str]:
    samples = scenario.get("samples", [])
    passed_samples = sum(bool(sample.get("passed")) for sample in samples)
    lines = [
        "",
        f"## Scenario: {_plain_name(scenario['scenario_id'])}",
        "",
        f"**Result:** {'PASS' if scenario.get('passed') else 'FAIL'} — "
        f"{passed_samples}/{len(samples)} conversations passed.",
    ]
    for sample in samples:
        lines.extend(
            [
                "",
                f"### Conversation {sample['sample_index'] + 1} — "
                f"{'PASS' if sample.get('passed') else 'FAIL'}",
                "",
            ]
        )
        if sample.get("error"):
            lines.extend([f"**Error:** the conversation could not run: {sample['error']}", ""])
        grades = {grade["turn_index"]: grade for grade in sample.get("grades", [])}
        for turn in sample.get("turns", []):
            lines.extend(
                [
                    f"**User:** {turn.get('user_message', '')}",
                    "",
                    f"**Companion:** {turn.get('assistant_reply', '') or '(no reply)'}",
                    "",
                ]
            )
            grade = grades.get(turn["turn_index"])
            if grade:
                score = grade.get("weighted_score")
                score_text = f" — {score:.1f}/4" if score is not None else ""
                lines.append(
                    f"**Turn result:** {'PASS' if grade.get('passed') else 'FAIL'}{score_text}"
                )
                for dimension in grade.get("dimension_grades", []):
                    lines.append(
                        f"- {_plain_name(dimension['dimension_id'])}: "
                        f"{dimension['score']}/4 — {dimension['reason']}"
                    )
                for finding in grade.get("findings", []):
                    lines.append(f"- Problem: {finding['message']}")
                if grade.get("judge_error"):
                    lines.append(f"- Judge error: {grade['judge_error']}")
                lines.append("")
    return lines


def _simulated_conversations_markdown(payload: dict[str, Any]) -> list[str]:
    simulated_user = payload.get("simulated_user") or {}
    judgment = payload.get("user_judgment") or {}
    independent_judgments = payload.get("independent_judgments") or []
    consensus = payload.get("consensus") or {}
    user_status = "PASS" if judgment.get("passed") else "FAIL"
    continuation = "yes" if judgment.get("would_continue") else "no"
    consensus_status = _result_label(payload)
    lines = [
        "## AI user",
        "",
        f"**Model:** {simulated_user.get('provider', 'unknown')} / "
        f"{simulated_user.get('model', 'provider-default')}",
        "",
        "## Consensus",
        "",
        f"**Final verdict:** {consensus_status}",
        f"**Voices passed:** {consensus.get('passing_voices', 0)}/"
        f"{consensus.get('total_voices', 0)}",
        f"**Consensus score:** {_score_text(consensus.get('average_score'))}",
        f"**Reason:** {consensus.get('reason', 'not provided')}",
    ]
    for disagreement in consensus.get("disagreements", []):
        lines.append(f"- Disagreement: {disagreement}")
    lines.extend(
        [
            "",
            "## AI-user verdict",
            "",
            f"**User verdict:** {user_status}",
            f"**Average score:** {judgment.get('average_score', 0):.1f}/4",
            f"**Would continue chatting:** {continuation}",
        ]
    )
    for dimension in judgment.get("dimensions", []):
        lines.append(
            f"- {_plain_name(dimension['dimension_id'])}: {dimension['score']}/4 — "
            f"{dimension['reason']}"
        )
    lines.extend(
        [
            "",
            f"**Overall reason:** {judgment.get('overall_reason', 'not provided')}",
            f"**Biggest problem:** {judgment.get('biggest_problem', 'not provided')}",
        ]
    )
    if independent_judgments:
        lines.extend(["", "## Independent judge verdicts"])
        for item in independent_judgments:
            status = "PASS" if item.get("passed") else "FAIL"
            lines.extend(
                [
                    "",
                    f"### {item.get('judge_name', 'Independent judge')} — {status}",
                    "",
                    f"**Average score:** {_score_text(item.get('average_score'))}",
                    f"**Would continue chatting:** {'yes' if item.get('would_continue') else 'no'}",
                ]
            )
            if item.get("error"):
                lines.append(f"**Judge error:** {item['error']}")
            for dimension in item.get("dimensions", []):
                lines.append(
                    f"- {_plain_name(dimension['dimension_id'])}: {dimension['score']}/4 — "
                    f"{dimension['reason']}"
                )
            lines.extend(
                [
                    f"**Overall reason:** {item.get('overall_reason', 'not provided')}",
                    f"**Biggest problem:** {item.get('biggest_problem', 'not provided')}",
                ]
            )
    checks = payload.get("deterministic_checks") or []
    if checks:
        lines.extend(["", "## Automatic conversation checks", ""])
        for check in checks:
            status = "PASS" if check.get("passed") else "FAIL"
            lines.append(
                f"- {_plain_name(check.get('id', 'check'))}: {status} — {check.get('reason', '')}"
            )
            if check.get("evidence"):
                lines.append(f"  - Evidence: {check['evidence']}")
    for conversation in payload.get("conversations", []):
        lines.extend(
            [
                "",
                f"## Conversation: {_plain_name(conversation['scenario_id'])}",
                "",
                f"**Stopped because:** {_plain_name(conversation.get('stop_reason', 'unknown'))}",
                "",
            ]
        )
        for turn in conversation.get("turns", []):
            lines.extend(
                [
                    f"**AI User:** {turn.get('user_message', '')}",
                    "",
                    f"**Companion:** {turn.get('assistant_reply', '') or '(no reply)'}",
                    "",
                ]
            )
    return lines


def _simulated_conversation_suite_markdown(payload: dict[str, Any]) -> list[str]:
    summary = payload.get("summary") or {}
    selection = payload.get("selection") or {}
    lines = [
        "## Suite summary",
        "",
        f"**Selected scenarios:** {summary.get('total', 0)}",
        f"**Passed:** {summary.get('passed', 0)}",
        f"**Failed:** {summary.get('failed', 0)}",
        f"**Pending:** {summary.get('pending', 0)}",
        f"**Average consensus score:** {_score_text(summary.get('average_score'))}",
        f"**Selection:** {_suite_selection_text(selection)}",
    ]
    for conversation in payload.get("conversations", []):
        status = _result_label(conversation)
        consensus = conversation.get("consensus") or {}
        scenario_id = (conversation.get("conversations") or [{}])[0].get(
            "scenario_id",
            "unknown",
        )
        lines.extend(
            [
                "",
                f"## Scenario: {_plain_name(scenario_id)}",
                "",
                f"**Result:** {status}",
                f"**Consensus score:** {_score_text(consensus.get('average_score'))}",
                f"**Reason:** {consensus.get('reason', 'not provided')}",
            ]
        )
        lines.extend(_simulated_conversations_markdown(conversation))
    return lines


def _conversation_judge_calibration_markdown(payload: dict[str, Any]) -> list[str]:
    calibration = payload.get("conversation_judge_calibration") or {}
    lines = [
        "## Conversation judge calibration",
        "",
        (
            f"Completed {calibration.get('completed_cases', 0)}/"
            f"{calibration.get('total_cases', 0)} known transcript checks."
        ),
        f"**Failed cases:** {calibration.get('failed_cases', 0)}",
        f"**Judge errors:** {calibration.get('judge_errors', 0)}",
    ]
    for case in calibration.get("cases", []):
        status = "PASS" if case.get("passed") else "FAIL"
        lines.extend(
            [
                "",
                f"- **{_plain_name(case.get('id', 'unknown'))}:** {status}; "
                f"expected={'PASS' if case.get('expected_pass') else 'FAIL'}, "
                f"observed={'PASS' if case.get('observed_pass') else 'FAIL'}",
            ]
        )
        if case.get("error"):
            lines.append(f"  Error: {case['error']}")
        if case.get("reason"):
            lines.append(f"  Why this matters: {case['reason']}")
    return lines


def _thread_management_shadow_markdown(payload: dict[str, Any]) -> list[str]:
    """Explain expected versus proposed thread actions without exposing raw trace noise."""
    summary = payload.get("summary") or {}
    lines = [
        "## Thread-management summary",
        "",
        f"**Scenarios:** {summary.get('total', 0)}",
        f"**Passed:** {summary.get('passed', 0)}",
        f"**Failed:** {summary.get('failed', 0)}",
        "**Database writes from proposals:** disabled (shadow mode)",
    ]
    for scenario in payload.get("scenarios", []):
        scenario_input = scenario.get("input") or {}
        expected = scenario.get("expected") or {}
        observed = scenario.get("observed") or {}
        lines.extend(
            [
                "",
                f"## Scenario: {_plain_name(scenario.get('scenario_id', 'unknown'))}",
                "",
                f"**Result:** {'PASS' if scenario.get('passed') else 'FAIL'}",
                f"**Purpose:** {scenario.get('description', 'not provided')}",
                "",
                "### Conversation state",
                "",
            ]
        )
        existing_threads = scenario_input.get("existing_threads") or []
        if existing_threads:
            for thread in existing_threads:
                flags = [str(thread.get("status") or "unknown")]
                if thread.get("active"):
                    flags.append("active")
                if thread.get("from_previous_conversation"):
                    flags.append("previous conversation")
                lines.append(
                    f"- **{thread.get('title', 'Untitled')}** "
                    f"(`{thread.get('id', 'unknown')}`; {', '.join(flags)})"
                )
        else:
            lines.append("- No existing persistent threads.")
        for message in scenario_input.get("prior_messages") or []:
            speaker = "User" if message.get("role") == "user" else "Companion"
            lines.extend(["", f"**{speaker}:** {message.get('content', '')}"])
        lines.extend(
            [
                "",
                f"**Latest user message:** {scenario_input.get('user_message', '')}",
                "",
                "### Expected and observed",
                "",
                f"**Expected action:** {expected.get('operation', 'none')}",
                f"**Expected thread:** {expected.get('thread_id') or 'none/new thread'}",
                f"**Why:** {expected.get('reason', 'not provided')}",
                "",
                f"**Companion reply:** {observed.get('assistant_reply') or '(no reply)'}",
                f"**Observed actions:** {', '.join(observed.get('operations') or []) or 'none'}",
                f"**Shadow proposal present:** {'yes' if observed.get('shadow_present') else 'no'}",
                f"**Structurally valid:** {'yes' if observed.get('shadow_valid') else 'no'}",
                f"**Finding:** {scenario.get('finding', 'not provided')}",
            ]
        )
        errors = observed.get("validation_errors") or []
        if errors:
            lines.extend(["", "**Validation problems:**"])
            lines.extend(f"- {error}" for error in errors)
        updates = (observed.get("proposal") or {}).get("thread_updates") or []
        if updates:
            lines.extend(["", "**Proposed updates:**"])
            for update in updates:
                operation = update.get("operation", "unknown")
                target = update.get("thread_id") or (update.get("thread") or {}).get("title")
                lines.append(f"- {operation}: {target or 'unspecified thread'}")
    return lines


def _memory_shadow_markdown(payload: dict[str, Any]) -> list[str]:
    """Render memory behavior in simple terms while retaining exact evidence indexes."""
    summary = payload.get("summary") or {}
    is_v3 = payload.get("stage") == "memory_v3_eval"
    lines = [
        "## Canonical-memory summary" if is_v3 else "## Background-memory summary",
        "",
        f"**Scenarios:** {summary.get('total', 0)}",
        f"**Passed:** {summary.get('passed', 0)}",
        f"**Failed:** {summary.get('failed', 0)}",
        f"**Invalid model responses:** {summary.get('structural_failures', 0)}",
        "**Live memory writes:** disabled (evaluation does not persist proposals)"
        if is_v3
        else "**Live memory writes:** disabled (shadow evaluation)",
    ]
    for scenario in payload.get("scenarios", []):
        scenario_input = scenario.get("input") or {}
        expected = scenario.get("expected") or {}
        observed = scenario.get("observed") or {}
        lines.extend(
            [
                "",
                f"## Scenario: {_plain_name(scenario.get('scenario_id', 'unknown'))}",
                "",
                f"**Result:** {'PASS' if scenario.get('passed') else 'FAIL'}",
                f"**Purpose:** {scenario.get('description', 'not provided')}",
                "",
                "### Conversation batch",
                "",
            ]
        )
        for index, message in enumerate(scenario_input.get("messages") or []):
            speaker = "User" if message.get("role") == "user" else "Companion"
            scope = (
                "context only"
                if index <= scenario_input.get("processed_through_message_index", -1)
                else "new"
            )
            lines.append(f"- **{speaker} [{index}, {scope}]:** {message.get('content', '')}")
        existing = scenario_input.get("existing_memories") or []
        lines.extend(["", "### Existing memory supplied", ""])
        if existing:
            for memory in existing:
                lines.append(
                    f"- `{memory.get('id', 'unknown')}` — "
                    f"{memory.get('label') or memory.get('key') or 'unlabelled'}: {memory.get('value')!r}"
                )
        else:
            lines.append("- None.")
        lines.extend(
            [
                "",
                "### Expected and observed",
                "",
                f"**Expected decision:** {expected.get('decision', 'unknown')}",
                f"**Observed decision:** {observed.get('decision', 'unknown')}",
                f"**Structurally valid:** {'yes' if observed.get('structurally_valid') else 'no'}",
                f"**Duration:** {observed.get('duration_seconds', 0):.1f} seconds",
            ]
        )
        expected_operations = expected.get("operations") or []
        lines.append("**Expected operations:**")
        if expected_operations:
            for operation in expected_operations:
                memory_type = (
                    operation.get("memory_kind")
                    or operation.get("data_point_type")
                    or "existing memory"
                )
                purposes = operation.get("required_purposes") or []
                purpose_text = f" / purposes={purposes}" if purposes else ""
                lines.append(
                    "- "
                    f"{operation.get('operation')} / {memory_type}{purpose_text} / "
                    f"concepts={operation.get('value_concepts') or []} / "
                    f"evidence={operation.get('evidence_message_indexes') or []}"
                )
        else:
            lines.append("- None.")
        optional_operations = expected.get("optional_operations") or []
        if optional_operations:
            lines.append("**Optional valid operations:**")
            for operation in optional_operations:
                memory_type = (
                    operation.get("memory_kind")
                    or operation.get("data_point_type")
                    or "existing memory"
                )
                purposes = operation.get("required_purposes") or []
                purpose_text = f" / purposes={purposes}" if purposes else ""
                lines.append(
                    "- "
                    f"{operation.get('operation')} / {memory_type}{purpose_text} / "
                    f"concepts={operation.get('value_concepts') or []} / "
                    f"evidence={operation.get('evidence_message_indexes') or []}"
                )
        observed_operations = observed.get("operations") or []
        lines.append("**Observed operations:**")
        if observed_operations:
            for operation in observed_operations:
                target = operation.get("target_memory_id") or "new memory"
                memory_type = (
                    operation.get("memory_kind")
                    or operation.get("data_point_type")
                    or "existing memory"
                )
                purposes = operation.get("purposes") or []
                purpose_text = f" / purposes={purposes}" if purposes else ""
                label = operation.get("label") or operation.get("key") or "unlabelled"
                lines.append(
                    "- "
                    f"{operation.get('operation')} / {memory_type}{purpose_text} / "
                    f"{label}: {operation.get('value')!r} / "
                    f"target={target} / evidence={operation.get('evidence_message_indexes') or []}"
                )
        else:
            lines.append("- None.")
        semantic_judgment = observed.get("semantic_judgment") or {}
        semantic_judge_error = observed.get("semantic_judge_error")
        if semantic_judgment or semantic_judge_error:
            lines.extend(["", "### Semantic evidence review", ""])
            if semantic_judge_error:
                lines.append(f"**Judge error:** {semantic_judge_error}")
            else:
                lines.extend(
                    [
                        f"**Judge:** {semantic_judgment.get('judge_name', 'unknown')}",
                        f"**Result:** {'PASS' if semantic_judgment.get('passed') else 'FAIL'}",
                        f"**Reason:** {semantic_judgment.get('overall_reason', 'not provided')}",
                    ]
                )
                for item in semantic_judgment.get("operations") or []:
                    issues = (
                        ", ".join(_plain_name(issue) for issue in item.get("issues") or [])
                        or "none"
                    )
                    lines.append(
                        f"- Operation {item.get('index', '?')}: "
                        f"{'supported' if item.get('supported') else 'rejected'}; "
                        f"issues={issues}; {item.get('reason', 'no reason')}"
                    )
        lines.extend(["", "**Findings:**"])
        lines.extend(f"- {finding}" for finding in scenario.get("findings") or ["None."])
        validation_errors = observed.get("validation_errors") or []
        if validation_errors:
            lines.extend(["", "**Validation problems:**"])
            lines.extend(f"- {error}" for error in validation_errors)
    return lines


def _improvement_targets_markdown(payload: dict[str, Any]) -> list[str]:
    targets = payload.get("improvement_targets") or []
    lines = ["", "## Improvement targets", ""]
    if not targets:
        lines.append("No improvement targets were generated from this run.")
        return lines
    for target in targets:
        evidence = target.get("evidence") or {}
        lines.extend(
            [
                (
                    f"- **{_plain_name(target.get('dimension_id', 'overall'))}:** "
                    f"{target.get('problem', 'No problem text provided')}"
                ),
                f"  Suggested area: {target.get('suggested_area', 'companion behavior')}",
                f"  Scenario: {target.get('scenario_id', 'unknown')}",
                f"  Evidence: user='{evidence.get('user_message', '')}' | "
                f"companion='{evidence.get('assistant_reply', '')}'",
            ]
        )
    return lines


def _human_review_markdown(payload: dict[str, Any]) -> list[str]:
    review = payload.get("human_review") or {}
    return [
        "",
        "## Human review",
        "",
        f"**Status:** {review.get('status', 'pending')}",
        "**Decision:** pending",
        "**Reviewer notes:** not added",
    ]


def _simple_summary(payload: dict[str, Any]) -> str:
    if payload.get("stage") == "execution_error":
        return f"The evaluation stopped because of a technical error: {payload['execution_error']}"
    if payload.get("stage") == "judge_calibration":
        if payload.get("passed"):
            return "The judge models passed their reliability check. No companion scenario was run."
        return (
            "The judge models were not reliable enough, so companion testing stopped before "
            "the conversation scenarios began."
        )
    if payload.get("stage") == "memory_judge_calibration":
        calibration = payload.get("judge_calibration") or {}
        return (
            "The memory evidence judge was checked against known correct and incorrect "
            f"proposals. Passed cases: {sum(bool(case.get('passed')) for case in calibration.get('cases', []))}/"
            f"{calibration.get('total_cases', 0)}; issue mismatches: "
            f"{calibration.get('issue_mismatches', 0)}; errors: "
            f"{calibration.get('judge_errors', 0)}."
        )

    if payload.get("stage") == "simulated_conversation":
        turn_count = sum(
            len(conversation.get("turns", [])) for conversation in payload.get("conversations", [])
        )
        judgment = payload.get("user_judgment") or {}
        user_status = "PASS" if judgment.get("passed") else "FAIL"
        return (
            f"An AI model acted as the user for {turn_count} conversation turns and judged "
            f"the experience {user_status} ({judgment.get('average_score', 0):.1f}/4). "
            f"The consensus result is {_result_label(payload)}."
        )
    if payload.get("stage") == "simulated_conversation_suite":
        summary = payload.get("summary") or {}
        return (
            f"The simulated suite ran {summary.get('total', 0)} scenarios: "
            f"{summary.get('passed', 0)} passed, {summary.get('failed', 0)} failed, "
            f"{summary.get('pending', 0)} pending. Average score: "
            f"{_score_text(summary.get('average_score'))}."
        )
    if payload.get("stage") == "conversation_judge_calibration":
        calibration = payload.get("conversation_judge_calibration") or {}
        return (
            "The independent full-conversation judges were checked against known good and "
            f"bad transcripts. Failed cases: {calibration.get('failed_cases', 0)}; "
            f"errors: {calibration.get('judge_errors', 0)}."
        )
    if payload.get("stage") == "thread_management_shadow_eval":
        summary = payload.get("summary") or {}
        total = summary.get("total", 0)
        scenario_word = "scenario" if total == 1 else "scenarios"
        return (
            f"The companion proposed thread actions for {total} {scenario_word}: "
            f"{summary.get('passed', 0)} matched expectations and "
            f"{summary.get('failed', 0)} did not. No proposed changes were persisted."
        )
    if payload.get("stage") in {"memory_shadow_eval", "memory_v3_eval"}:
        summary = payload.get("summary") or {}
        lane = (
            "canonical V3 memory model"
            if payload.get("stage") == "memory_v3_eval"
            else "background memory model"
        )
        return (
            f"The {lane} analyzed {summary.get('total', 0)} realistic "
            f"conversation batches: {summary.get('passed', 0)} matched expectations and "
            f"{summary.get('failed', 0)} did not. No live memories were changed."
        )
    passed = payload.get("scenario_passed", 0)
    failed = payload.get("scenario_failed", 0)
    return f"The companion passed {passed} scenarios and failed {failed}."


def _bottom_line(payload: dict[str, Any]) -> str:
    if payload.get("stage") == "execution_error":
        return (
            "Fix the technical error and run the evaluation again; this run has no quality verdict."
        )
    if payload.get("stage") == "judge_calibration":
        return (
            "Do not trust or compare companion scores from this run because the judge check "
            "did not complete successfully. This run has no quality verdict for the companion."
            if not payload.get("passed")
            else "The judges are ready for a companion evaluation run."
        )
    if payload.get("stage") == "memory_judge_calibration":
        return (
            "The memory evidence judge is calibrated and ready for the memory suite."
            if payload.get("passed")
            else "Do not trust semantic memory verdicts from this judge until calibration passes."
        )

    if payload.get("stage") == "simulated_conversation":
        return (payload.get("consensus") or {}).get(
            "reason",
            "The simulated conversation was judged by the available evaluation voices.",
        )
    if payload.get("stage") == "simulated_conversation_suite":
        summary = payload.get("summary") or {}
        if payload.get("passed"):
            return "Every selected simulated conversation passed consensus."
        return (
            "At least one selected simulated conversation failed or is pending. "
            f"Passed: {summary.get('passed', 0)}, failed: {summary.get('failed', 0)}, "
            f"pending: {summary.get('pending', 0)}."
        )
    if payload.get("stage") == "conversation_judge_calibration":
        return (
            "The full-conversation judge calibration passed."
            if payload.get("passed")
            else "Do not trust full-conversation verdicts from this judge until calibration passes."
        )
    if payload.get("stage") == "thread_management_shadow_eval":
        summary = payload.get("summary") or {}
        if payload.get("passed"):
            return "Every selected thread-management proposal matched the expected action."
        failed = [
            _plain_name(item.get("scenario_id", "unknown"))
            for item in payload.get("scenarios", [])
            if not item.get("passed")
        ]
        return (
            f"Thread management needs improvement in {len(failed)} scenario(s): "
            + ", ".join(failed)
            + "."
        )
    if payload.get("stage") in {"memory_shadow_eval", "memory_v3_eval"}:
        summary = payload.get("summary") or {}
        if payload.get("passed"):
            return "Every selected memory proposal matched the expected safe behavior."
        failed = [
            _plain_name(item.get("scenario_id", "unknown"))
            for item in payload.get("scenarios", [])
            if not item.get("passed")
        ]
        return (
            f"Memory extraction needs improvement in {len(failed)} scenario(s): "
            + ", ".join(failed)
            + "."
        )
    if payload.get("passed"):
        return "This companion configuration passed every selected release scenario."
    failed = [
        _plain_name(item["scenario_id"])
        for item in payload.get("scenarios", [])
        if not item.get("passed")
    ]
    return "The companion needs improvement in: " + ", ".join(failed) + "."


def _calibration_failure_reason(case: dict[str, Any]) -> str:
    if case.get("expected_pass") and not case.get("observed_pass"):
        return "The judge rejected an answer that should pass."
    if not case.get("expected_pass") and case.get("observed_pass"):
        return "The judge accepted an answer that should fail."
    return "The judge result did not match the known answer."


def _report_stem(payload: dict[str, Any], timestamp: datetime) -> str:
    local_time = timestamp.astimezone(REPORT_TIMEZONE)
    stamp = local_time.strftime("%H%M%S_%f")[:-3]
    stage = {
        "behavior_evaluation": "behavior",
        "simulated_conversation": "simulated",
        "simulated_conversation_suite": "sim_suite",
        "conversation_judge_calibration": "conv_judge_calibration",
        "thread_management_shadow_eval": "thread_shadow",
        "memory_judge_calibration": "memory_judge_calibration",
        "memory_shadow_eval": "memory_shadow",
        "memory_v3_eval": "memory_v3",
        "memory_retrieval_stress_eval": "memory_retrieval",
        "memory_retrieval_cases_eval": "memory_retrieval_cases",
        "judge_calibration": "calibration",
        "execution_error": "error",
    }.get(str(payload.get("stage") or ""), "evaluation")
    status = {
        "PENDING INDEPENDENT JUDGE": "pending",
        "UNSCORED": "unscored",
        "PASS": "pass",
        "FAIL": "fail",
    }[_result_label(payload)]
    return f"{stamp}__{stage}__{status}"


def _append_history(
    history_path: Path,
    payload: dict[str, Any],
    timestamp: datetime,
) -> None:
    if history_path.exists():
        existing = history_path.read_text(encoding="utf-8").rstrip()
    else:
        existing = (
            "# Evaluation History\n\nSynthetic evaluation scores are grouped by day for comparison."
        )
    companion = payload.get("companion") or {}
    run = payload.get("run") or {}
    passed_text = (
        f"{payload.get('scenario_passed', 0)}/"
        f"{payload.get('scenario_passed', 0) + payload.get('scenario_failed', 0)} scenarios"
        if payload.get("stage") == "behavior_evaluation"
        else (
            f"{sum(len(item.get('turns', [])) for item in payload.get('conversations', []))} turns"
            if payload.get("stage") == "simulated_conversation"
            else (
                f"{payload.get('summary', {}).get('passed', 0)}/"
                f"{payload.get('summary', {}).get('total', 0)} scenarios"
                if payload.get("stage")
                in {
                    "simulated_conversation_suite",
                    "thread_management_shadow_eval",
                    "memory_shadow_eval",
                    "memory_v3_eval",
                    "memory_retrieval_stress_eval",
                    "memory_retrieval_cases_eval",
                }
                else (
                    f"{payload.get('conversation_judge_calibration', {}).get('completed_cases', 0)}/"
                    f"{payload.get('conversation_judge_calibration', {}).get('total_cases', 0)} checks"
                    if payload.get("stage") == "conversation_judge_calibration"
                    else f"{payload.get('judge_calibration', {}).get('completed_cases', 0)}/"
                    f"{payload.get('judge_calibration', {}).get('total_cases', 0)} judge checks"
                )
            )
        )
    )
    day = _history_day(timestamp)
    row = (
        f"| {_history_time(run.get('finished_at'), timestamp)} | "
        f"{_result_label(payload)} | "
        f"{_plain_name(payload.get('stage', 'unknown'))} | "
        f"{_table_text(str(companion.get('model', 'provider-default')))} | "
        f"{_history_score(payload)} | {passed_text} |"
    )
    section_header = f"## {day}"
    table_header = (
        "| Time (IST) | Result | Stage | Companion | Score | Passed |\n"
        "| --- | --- | --- | --- | --- | --- |"
    )
    if section_header not in existing:
        updated = f"{existing}\n\n{section_header}\n\n{table_header}\n{row}\n"
    else:
        section_start = existing.index(section_header)
        next_section = existing.find("\n## ", section_start + len(section_header))
        insert_at = len(existing) if next_section == -1 else next_section
        updated = (
            existing[:insert_at].rstrip()
            + "\n"
            + row
            + ("\n" if next_section == -1 else "\n\n")
            + existing[insert_at:].lstrip()
        )
    _write_text_atomic(history_path, updated)


def _history_score(payload: dict[str, Any]) -> str:
    if payload.get("stage") in {
        "thread_management_shadow_eval",
        "memory_shadow_eval",
        "memory_v3_eval",
        "memory_retrieval_stress_eval",
        "memory_retrieval_cases_eval",
    }:
        summary = payload.get("summary") or {}
        total = summary.get("total", 0)
        passed = summary.get("passed", 0)
        return f"{(passed / total) * 100:.0f}%" if total else "—"
    if payload.get("stage") == "simulated_conversation_suite":
        score = (payload.get("summary") or {}).get("average_score")
        return f"{score:.1f}/4" if isinstance(score, (int, float)) else "—"
    if payload.get("stage") == "simulated_conversation":
        score = (payload.get("consensus") or {}).get("average_score")
        if not isinstance(score, (int, float)):
            score = (payload.get("user_judgment") or {}).get("average_score")
        return f"{score:.1f}/4" if isinstance(score, (int, float)) else "—"
    scores = [
        grade.get("weighted_score")
        for scenario in payload.get("scenarios", [])
        for sample in scenario.get("samples", [])
        for grade in sample.get("grades", [])
        if isinstance(grade.get("weighted_score"), (int, float))
    ]
    return f"{sum(scores) / len(scores):.1f}/4" if scores else "—"


def _history_day(timestamp: datetime) -> str:
    return timestamp.astimezone(REPORT_TIMEZONE).strftime("%Y-%m-%d")


def _history_time(value: Any, fallback: datetime) -> str:
    parsed = _parse_datetime(value) or fallback
    return parsed.astimezone(REPORT_TIMEZONE).strftime("%H:%M:%S")


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _plain_name(value: str) -> str:
    return value.replace("_", " ").strip().capitalize()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "unknown"


def _display_time(value: Any) -> str:
    parsed = _parse_datetime(value)
    return (
        parsed.astimezone(REPORT_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S IST")
        if parsed
        else "unknown"
    )


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _table_text(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _result_label(payload: dict[str, Any]) -> str:
    if (
        payload.get("stage") == "simulated_conversation"
        and payload.get("verdict") == "pending_independent_judge"
    ):
        return "PENDING INDEPENDENT JUDGE"
    if payload.get("passed") is None:
        return "UNSCORED"
    return "PASS" if payload.get("passed") else "FAIL"


def _score_text(value: Any) -> str:
    return f"{value:.1f}/4" if isinstance(value, (int, float)) else "not available"


def _suite_selection_text(selection: dict[str, Any]) -> str:
    scenarios = selection.get("scenario_ids") or []
    tags = selection.get("tags") or []
    parts = []
    if tags:
        parts.append("tags=" + ",".join(str(tag) for tag in tags))
    if scenarios:
        parts.append("scenarios=" + ",".join(str(item) for item in scenarios))
    return "; ".join(parts) if parts else "default scenario"


def _memory_judge_calibration_markdown(calibration: dict[str, Any]) -> list[str]:
    """Render every known memory-judge example with its input and verdict."""
    lines = [
        "## Judge reliability check",
        "",
        (
            f"The judge completed {calibration.get('completed_cases', 0)}/"
            f"{calibration.get('total_cases', 0)} known examples. "
            f"Errors: {calibration.get('judge_errors', 0)}. "
            f"Result: {'PASS' if calibration.get('passed') else 'FAIL'}."
        ),
        "",
        "## Memory judge calibration cases",
    ]
    for case in calibration.get("cases") or []:
        lines.extend(
            [
                "",
                f"### {_plain_name(case.get('id', 'unknown'))}",
                "",
                f"**Result:** {'PASS' if case.get('passed') else 'FAIL'}",
                "",
                "**Evidence:**",
            ]
        )
        evidence = case.get("evidence_messages") or []
        if evidence:
            lines.extend(f"- {message}" for message in evidence)
        else:
            lines.append("- None.")
        lines.extend(["", "**Proposed memories:**"])
        proposals = case.get("proposed_operations") or []
        if proposals:
            for operation in proposals:
                memory_type = (
                    operation.get("memory_kind") or operation.get("data_point_type") or "unknown"
                )
                purposes = operation.get("purposes") or []
                purpose_text = f" / purposes={purposes}" if purposes else ""
                lines.append(
                    f"- {memory_type}{purpose_text} / "
                    f"{operation.get('label') or operation.get('key') or 'unlabelled'}: "
                    f"{operation.get('value')!r}"
                )
        else:
            lines.append("- None.")
        for index, operation in enumerate(case.get("operations") or [], start=1):
            required = (
                ", ".join(_plain_name(issue) for issue in operation.get("required_issues") or [])
                or "none"
            )
            observed_issues = (
                ", ".join(_plain_name(issue) for issue in operation.get("observed_issues") or [])
                or "none"
            )
            expected_status = "supported" if operation.get("expected_supported") else "rejected"
            observed_status = "supported" if operation.get("observed_supported") else "rejected"
            lines.extend(
                [
                    "",
                    f"**Operation {index}:**",
                    f"- Expected: {expected_status}; issues: {required}",
                    f"- Observed: {observed_status}; issues: {observed_issues}",
                    f"- Judge reason: {operation.get('reason', 'not provided')}",
                ]
            )
        problem = case.get("judge_error") or case.get("failure_reason")
        if problem:
            lines.extend(["", f"**Problem:** {problem}"])
    return lines
