"""Warns about staged changes that can break things quietly. It never blocks a commit.

Run by .git/hooks/pre-commit, or by hand: python scripts/commit_check.py --all
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP_FILE = ROOT / "docs" / "problem-map.json"
PLAN_DOCS = {"docs/problem.md", "docs/production-plan.md", "docs/progress.md"}
ROOM_WARNING = 100


def staged_files() -> set[str]:
    done = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return set(done.stdout.splitlines())


def check_prompt_blocks() -> list[str]:
    """The omi block is cut with no warning past its limit, which lost the voice rules once."""
    sys.path.insert(0, str(ROOT / "src"))
    from agent.context_engine.prompt_engine.blocks import BLOCK_CHAR_LIMITS
    from agent.context_engine.prompt_engine.modules.identity import voice_prompt
    from agent.context_engine.prompt_engine.modules.tone import tone_module_prompt
    from agent.context_engine.prompt_engine.registry import available_prompt_versions

    limit = BLOCK_CHAR_LIMITS["omi"]
    longest_tone = max(
        (tone_module_prompt(tone) for tone in ("casual", "warm", "formal", "direct", "playful")), key=len
    )
    notes = []
    for version in available_prompt_versions():
        if not version.blocks_prompt:
            continue
        parts = (version.base_prompt, voice_prompt("neutral"), longest_tone)
        size = len("\n\n".join(part.strip() for part in parts))
        if size > limit:
            notes.append(f"{version.version_id}: omi block is {size} of {limit}, so its end will be cut")
        elif limit - size < ROOM_WARNING:
            notes.append(f"{version.version_id}: omi block is {size} of {limit}, only {limit - size} characters left")
    return notes


def check_problem_map(staged: set[str], everything: bool) -> list[str]:
    """Quotes the map rests on must still exist, and docs that changed may settle its open points."""
    if not MAP_FILE.exists():
        return []
    try:
        data = json.loads(MAP_FILE.read_text(encoding="utf-8"))
    except ValueError:
        return ["docs/problem-map.json is not valid JSON"]

    problems = data["problems"] if isinstance(data.get("problems"), list) else [data]
    notes = []
    for problem in problems:
        for link in problem.get("links", []):
            for source in link.get("sources", []):
                file = str(source.get("file", ""))
                if not everything and file not in staged:
                    continue
                path = ROOT / file
                words = str(source.get("quote", "")).split()
                pattern = r"\s+".join(re.escape(word) for word in words)
                text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
                if not words or not re.search(pattern, text, re.IGNORECASE):
                    notes.append(f'problem map, "{link.get("name")}": quote no longer found in {file}')

    open_points = sum(len(problem.get("disagreements", [])) for problem in problems)
    if open_points and (everything or staged & PLAN_DOCS):
        notes.append(f"problem map lists {open_points} points where the plan docs disagree; check if this settles any")
    return notes


def main() -> int:
    everything = "--all" in sys.argv
    staged = staged_files()
    notes: list[str] = []
    if everything or any("prompt_engine" in path for path in staged):
        try:
            notes += check_prompt_blocks()
        except Exception as error:  # A broken check must never stop a commit.
            notes.append(f"prompt block check could not run: {type(error).__name__}")
    notes += check_problem_map(staged, everything)

    if notes:
        print("commit check (a warning, the commit still goes ahead):", file=sys.stderr)
        for note in notes:
            print(f"  - {note}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
