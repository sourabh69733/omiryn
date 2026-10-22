#!/usr/bin/env python3
"""Run the uploaded-chat eval: is a WhatsApp chat read right, and can Omi answer about it?

Reads a fixed chat with the real upload models, then asks the real reply model 12 questions in fresh
chats (facts, quotes, dates, traps, small talk). Uses a separate SQLite test database. No AI judge:
checked in code. Prints the results and saves a Markdown report.

    PYTHONPATH=src python scripts/evals/run_upload_chat_evals.py --runs 1
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
EXPLICIT_DATABASE_URL = os.environ.get("DATABASE_URL")
load_dotenv(PROJECT_ROOT / ".env")
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
os.environ["DATABASE_URL"] = EXPLICIT_DATABASE_URL or "sqlite:///./data/omiryn_upload_chat_test.db"

from agent.evals.memory.upload_chats import QUESTIONS, ask, read_upload_case  # noqa: E402
from storage import reset_db  # noqa: E402

_PROVIDER_TRIES = 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=1, help="Full runs: one read and every question (default 1).")
    parser.add_argument("--question", action="append", dest="question_ids", help="Only these questions.")
    parser.add_argument("--no-save", action="store_true")
    return parser


async def _run(args: argparse.Namespace) -> int:
    os.environ.update({"AGENT_PIPELINE_VERSION": "v3", "AGENT_PROVIDER": "deepinfra", "MEMORY_EMBEDDING_MODEL": "off"})
    reply_model = os.environ.get("DEEPINFRA_MODEL") or "default"
    questions = [q for q in QUESTIONS if not args.question_ids or q.id in args.question_ids]
    reset_db()
    lines = ["# Uploaded chat eval", "", f"Reply `{reply_model}` · {args.runs} run(s)", ""]
    total = passed = 0
    for run in range(1, args.runs + 1):
        user_id, reading = await read_upload_case()
        total += 1
        passed += not reading.problems
        status = "PASS" if not reading.problems else "FAIL: " + "; ".join(reading.problems)
        print(f"run {run} reading: {status} ({reading.seconds}s, {reading.learned} memories, {reading.topics} topics)")
        lines += [f"## Run {run}", "", f"- Reading: {status} ({reading.seconds}s, {reading.learned} memories, {reading.topics} topics)"]
        lines.append(f"  - index: {reading.digest.get('index_line')}")
        lines.append(f"  - summary: {reading.digest.get('summary')}")
        lines.extend(f"  - topic: {t.get('title')} [{t.get('started')}]: {t.get('summary')}" for t in reading.digest.get("threads") or [])
        lines.extend(f"  - about {reading.digest.get('chat_with')}: {p.get('text')}" for p in reading.digest.get("person") or [])
        lines.extend(f"  - memory: {memory}" for memory in reading.memories)
        for question in questions:
            for attempt in range(_PROVIDER_TRIES):
                try:
                    result = await ask(user_id, question)
                    break
                except Exception as error:  # provider hiccup
                    if attempt == _PROVIDER_TRIES - 1:
                        raise
                    print(f"  retry {question.id}: {type(error).__name__}")
                    await asyncio.sleep(5)
            total += 1
            passed += result.passed
            mark = "PASS" if result.passed else f"FAIL ({result.problem})"
            print(f"  {question.id}: {mark}")
            lines.append(f"- {question.id}: {mark}\n  - Q: {question.text}\n  - A: {result.reply}")
        lines.append("")
    summary = f"Total: {passed}/{total} passed"
    print(summary)
    lines.insert(3, summary)
    if not args.no_save:
        folder = PROJECT_ROOT / "reports" / "evals" / datetime.now().strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{datetime.now().strftime('%H%M%S')}__upload_chats.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Report: {path}")
    return 0 if passed == total else 1


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
