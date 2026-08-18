"""Verifies required context and prompt instructions survive constrained budgets."""

from __future__ import annotations

import unittest

from agent.context_engine.assembly.budget import budget_context_sources
from agent.context_engine.prompt_engine.structure import (
    PromptSection,
    PromptStructureContext,
    structure_prompt_sections,
)


class ContextBudgetingTest(unittest.TestCase):
    def test_thread_candidates_win_over_optional_sources_under_pressure(self) -> None:
        sources = [
            {"source_type": "manual_notes", "content": "m" * 500},
            {"source_type": "conversation_threads", "content": "thread_id=required"},
            {"source_type": "chat_export", "content": "c" * 500},
        ]

        selected = budget_context_sources(sources, total_budget=300, source_limit=1)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].source["source_type"], "conversation_threads")

    def test_non_skippable_prompt_sections_are_reserved_before_optional_sections(self) -> None:
        sections = [
            PromptSection(
                id="base_identity",
                title="Identity",
                content="identity " * 30,
                position="start",
                priority=100,
                can_skip=False,
            ),
            PromptSection(
                id="optional_context",
                title="Optional",
                content="optional " * 60,
                position="middle",
                priority=90,
            ),
            PromptSection(
                id="output_format",
                title="Output",
                content="required output format",
                position="end",
                priority=100,
                can_skip=False,
            ),
        ]
        context = PromptStructureContext(
            intent_labels=frozenset(),
            source_types=frozenset(),
            has_context=False,
            has_data_points=False,
            has_whatsapp_context=False,
            is_low_information=False,
            has_emotion_state=False,
        )

        structured = structure_prompt_sections(sections, context, total_budget=150)

        included_ids = {section.id for section in structured.included_sections}
        self.assertIn("base_identity", included_ids)
        self.assertIn("output_format", included_ids)
        self.assertLessEqual(len(structured.text), 150)


if __name__ == "__main__":
    unittest.main()
