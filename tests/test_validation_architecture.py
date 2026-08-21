"""Protects one-way dependencies between validation, domains, and cognition."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = PROJECT_ROOT / "src" / "agent"


class ValidationArchitectureTest(unittest.TestCase):
    def test_shared_validation_helpers_have_no_imports(self) -> None:
        path = AGENT_ROOT / "shared" / "validation.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))

        imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]

        self.assertEqual(imports, [])

    def test_memory_validation_does_not_depend_on_workers_or_other_domains(self) -> None:
        source = (
            AGENT_ROOT / "memory_engine" / "processing" / "validation.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("processing.shadow", source)
        self.assertNotIn("agent.cognition", source)
        self.assertNotIn("agent.providers", source)
        self.assertNotIn("storage", source)

    def test_background_service_owns_cross_domain_orchestration(self) -> None:
        service = AGENT_ROOT / "cognition" / "background" / "service.py"
        source = service.read_text(encoding="utf-8")
        api_source = (
            PROJECT_ROOT / "src" / "api" / "routes" / "conversations.py"
        ).read_text(encoding="utf-8")

        self.assertIn("async def run_background_cognition", source)
        self.assertIn("agent.cognition.background", api_source)
        self.assertNotIn("memory_engine.processing.shadow", api_source)
        self.assertFalse(
            (AGENT_ROOT / "cognition" / "background" / "validation.py").exists()
        )


if __name__ == "__main__":
    unittest.main()
