from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.evals.behavior.live_reporter import LiveRunStats


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
    result = _result_label(payload)
    run = payload.get("run") or {}
    companion = payload.get("companion") or {}
    calibration = payload.get("judge_calibration") or {}
    lines = [
        "# Companion Evaluation Report",
        "",
        f"**Result:** {result}",
        f"**Finished:** {_display_time(run.get('finished_at'))}",
        f"**Companion agent:** {companion.get('agent_name', 'unknown')}",
        f"**Companion provider:** {companion.get('provider', 'unknown')}",
        f"**Companion model:** {companion.get('model', 'provider-default')}",
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
            reason = case.get("judge_error") or _calibration_failure_reason(case)
            lines.append(f"- **{_plain_name(case['id'])}:** {reason}")

    for scenario in payload.get("scenarios", []):
        lines.extend(_scenario_markdown(scenario))

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
    user_status = "PASS" if judgment.get("passed") else "FAIL"
    continuation = "yes" if judgment.get("would_continue") else "no"
    lines = [
        "## AI user",
        "",
        f"**Model:** {simulated_user.get('provider', 'unknown')} / "
        f"{simulated_user.get('model', 'provider-default')}",
        "",
        "## AI-user verdict",
        "",
        f"**User verdict:** {user_status}",
        f"**Average score:** {judgment.get('average_score', 0):.1f}/4",
        f"**Would continue chatting:** {continuation}",
    ]
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
    if payload.get("stage") == "simulated_conversation":
        turn_count = sum(
            len(conversation.get("turns", [])) for conversation in payload.get("conversations", [])
        )
        judgment = payload.get("user_judgment") or {}
        user_status = "PASS" if judgment.get("passed") else "FAIL"
        return (
            f"An AI model acted as the user for {turn_count} conversation turns and judged "
            f"the experience {user_status} ({judgment.get('average_score', 0):.1f}/4). "
            "The final result is pending an independent judge."
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
    if payload.get("stage") == "simulated_conversation":
        return (
            "The AI-user verdict reflects the simulated user's experience, but it is not the final "
            "release verdict. An independent judge must review the conversation next."
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
    scope = "calibration"
    scenarios = payload.get("scenarios") or []
    conversations = payload.get("conversations") or []
    if len(conversations) == 1:
        scope = conversations[0]["scenario_id"]
    elif len(scenarios) == 1:
        scope = scenarios[0]["scenario_id"]
    elif len(scenarios) > 1:
        scope = payload.get("suite_name") or "behavior_suite"
    companion = payload.get("companion") or {}
    model = companion.get("model") or "provider-default"
    status = _result_label(payload).casefold()
    stamp = timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d_%H%M%S_%fZ")[:-4] + "Z"
    return "__".join((_slug(stamp), _slug(scope), _slug(str(model)), status))


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
            else f"{payload.get('judge_calibration', {}).get('completed_cases', 0)}/"
            f"{payload.get('judge_calibration', {}).get('total_cases', 0)} judge checks"
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
        "| Time (UTC) | Result | Stage | Companion | Score | Passed |\n"
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
    if payload.get("stage") == "simulated_conversation":
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
    return timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _history_time(value: Any, fallback: datetime) -> str:
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        parsed = fallback
    return parsed.astimezone(timezone.utc).strftime("%H:%M:%S")


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
    if not value:
        return "unknown"
    return str(value).replace("T", " ").replace("+00:00", " UTC")


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
