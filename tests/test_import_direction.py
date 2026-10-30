"""Dependencies point one way: the agent uses storage, storage never uses the agent.

Storage may use `agent.shared` (clock, timeline, memory contracts, vibe helpers, fact taxonomy),
which itself imports nothing from storage or the rest of the agent. Everything else storage needs
from the agent is a sign the logic sits in the wrong place.
"""

import re
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE)


def _imports(path: Path) -> set[str]:
    return {match.group(1) or match.group(2) for match in IMPORT.finditer(path.read_text(encoding="utf-8"))}


class ImportDirectionTest(unittest.TestCase):
    def test_storage_imports_only_agent_shared_from_the_agent(self) -> None:
        offenders = {
            str(path.relative_to(SRC)): sorted(name for name in _imports(path) if name.startswith("agent") and not name.startswith("agent.shared"))
            for path in (SRC / "storage").glob("*.py")
        }
        self.assertEqual({path: names for path, names in offenders.items() if names}, {})

    def test_agent_shared_is_a_leaf(self) -> None:
        offenders = {
            str(path.relative_to(SRC)): sorted(
                name for name in _imports(path)
                if name.startswith(("storage", "api", "realtime", "security", "channels")) or (name.startswith("agent") and not name.startswith("agent.shared"))
            )
            for path in (SRC / "agent" / "shared").glob("*.py")
        }
        self.assertEqual({path: names for path, names in offenders.items() if names}, {})


if __name__ == "__main__":
    unittest.main()
