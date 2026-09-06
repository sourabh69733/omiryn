"""Covers deterministic fixtures, grading, and reports for retrieval stress."""

from __future__ import annotations

from datetime import UTC, datetime

import storage
from agent.evals.memory.retrieval_report import render_retrieval_stress_markdown
from agent.evals.memory.retrieval_stress import (
    RETRIEVAL_STRESS_MEMORY_COUNT,
    build_retrieval_stress_fixture,
    run_retrieval_stress_evaluation,
)


NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def setup_function() -> None:
    storage.reset_db()


def test_fixture_contains_all_memory_kinds_and_policy_traps() -> None:
    fixture = build_retrieval_stress_fixture()

    assert len(fixture) == RETRIEVAL_STRESS_MEMORY_COUNT
    assert {item.kind for item in fixture} == {
        "semantic",
        "episodic",
        "relationship",
        "procedural",
    }
    assert sum(item.relevant for item in fixture) == 5
    assert sum(item.expires == "past" for item in fixture) == 2
    assert sum(item.sensitivity == "highly_sensitive" for item in fixture) == 2
    assert sum("reply_context" not in item.allowed_uses for item in fixture) == 1


def test_real_retrieval_selects_only_expected_safe_memories() -> None:
    payload = run_retrieval_stress_evaluation(
        now=NOW,
        user_id="retrieval-stress-user",
        conversation_id="retrieval-stress-conversation",
    )

    metrics = payload["scenario"]["metrics"]
    assert payload["passed"] is True
    assert payload["summary"]["candidate_count"] == 100
    assert metrics["target_recall"] == 1.0
    assert metrics["precision_at_k"] == 1.0
    assert metrics["irrelevant_selected_count"] == 0
    assert metrics["policy_violation_count"] == 0
    assert metrics["selected_count"] == metrics["selection_limit"] == 5


def test_retrieval_report_explains_quality_and_safety_metrics() -> None:
    payload = run_retrieval_stress_evaluation(
        now=NOW,
        user_id="retrieval-report-user",
        conversation_id="retrieval-report-conversation",
    )
    payload["run"] = {"finished_at": NOW.isoformat()}

    report = render_retrieval_stress_markdown(payload)

    assert "100 synthetic candidates" in report
    assert "Relevant recall: 100%" in report
    assert "Policy violations: 0" in report
    assert "Model API calls:** 0" in report
