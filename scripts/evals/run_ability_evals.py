#!/usr/bin/env python3
"""Run the ability questions: can Omi do what people ask of a personal agent?

Each question goes through the real reply path for a made-up user in a fresh chat, with the real
reply model and the real tools (web search, places). A judge model marks each reply against the
written rule. Uses a separate SQLite test database, never the app's own. Saves a Markdown report.

    PYTHONPATH=src python scripts/evals/run_ability_evals.py --who student --area career
    PYTHONPATH=src python scripts/evals/run_ability_evals.py --question exams-gate-form

This makes real model and search calls, so it costs money: about 125 replies for the whole list.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
load_dotenv(PROJECT_ROOT / ".env")
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
# Always its own database: this script empties it before a run.
os.environ["DATABASE_URL"] = "sqlite:///./data/omiryn_abilities_test.db"

from agent.evals.abilities.questions import AREAS, NEEDS, QUESTIONS, WHO  # noqa: E402
from agent.evals.abilities.report import as_markdown, tally  # noqa: E402
from agent.evals.abilities.runner import REASONS, mark_saved, run, saved  # noqa: E402
from agent.providers.extraction.service import request_check_model  # noqa: E402
from agent.providers.shared.model_catalog import server_reply_model  # noqa: E402
from storage import reset_db, summarize_agent_usage  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--who", action="append", choices=list(WHO), help="Only these stages of life.")
    parser.add_argument("--area", action="append", choices=list(AREAS), help="Only these areas.")
    parser.add_argument("--needs", action="append", choices=list(NEEDS), help="Only these kinds of ask.")
    parser.add_argument("--question", action="append", dest="question_ids", help="Only these question ids.")
    parser.add_argument("--model", help="Reply model. Default: AGENT_REPLY_MODEL, else the provider's model.")
    parser.add_argument("--judge-model", help="Judge model. Default: the request check model.")
    parser.add_argument("--no-judge", action="store_true", help="Only what code can check.")
    parser.add_argument("--at-once", type=int, default=4, help="Chats running at the same time (default 4).")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--mark-again", metavar="RUN.json", help="Mark a saved run again with the judge. Asks Omi nothing.")
    return parser


async def _run(args: argparse.Namespace) -> int:
    os.environ.update({"AGENT_PIPELINE_VERSION": "v3", "AGENT_PROVIDER": "deepinfra", "MEMORY_EMBEDDING_MODEL": "off"})
    def show(asked, mark) -> None:
        verdict = "NOT MARKED" if mark.reason == "not_run" else mark.verdict.upper()
        print(f"{asked.question.id}: {verdict} ({REASONS[mark.reason]})", flush=True)

    if args.mark_again:
        return await _mark_again(args, show)
    questions = [
        question
        for question in QUESTIONS
        if (not args.who or question.who in args.who)
        and (not args.area or question.area in args.area)
        and (not args.needs or question.needs in args.needs)
        and (not args.question_ids or question.id in args.question_ids)
    ]
    if not questions:
        print("No question matches.")
        return 2
    reply_model = args.model or server_reply_model()
    judge_model = "none" if args.no_judge else (args.judge_model or request_check_model("deepinfra") or "default")
    print(f"{len(questions)} questions · reply {reply_model or 'provider default'} · judge {judge_model}")
    reset_db()
    results = await run(questions, model=reply_model, use_judge=not args.no_judge, judge_model=args.judge_model, at_once=args.at_once, on_done=show)
    cost = summarize_agent_usage(allow_app_wide=True).get("estimated_cost_usd")
    _finish(results, reply_model or "provider default", judge_model, datetime.now().astimezone(), cost, save=not args.no_save)
    return 0


async def _mark_again(args: argparse.Namespace, show) -> int:
    run_data = json.loads(Path(args.mark_again).read_text(encoding="utf-8"))
    judge_model = args.judge_model or request_check_model("deepinfra") or "default"
    print(f"{len(run_data['replies'])} saved replies · reply {run_data['reply_model']} · judge {judge_model}")
    reset_db()
    results = await mark_saved(run_data, judge_model=args.judge_model, at_once=args.at_once, on_done=show)
    cost = summarize_agent_usage(allow_app_wide=True).get("estimated_cost_usd")
    _finish(results, run_data["reply_model"], judge_model, datetime.fromisoformat(run_data["when"]), cost, save=not args.no_save, marked_again=True)
    return 0


def _finish(results, reply_model: str, judge_model: str, when: datetime, cost, *, save: bool, marked_again: bool = False) -> None:
    """Print the score; save the report and the run as data (replies and lookups) beside it."""
    counts = tally(results)
    print(f"Right {counts['right']} · partly {counts['partly']} · wrong {counts['wrong']} · not marked {counts['not_run']}" + (f" · ${cost:.2f}" if cost else ""))
    if not save:
        return
    now = datetime.now()
    folder = PROJECT_ROOT / "reports" / "evals" / now.strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{now.strftime('%H%M%S')}__abilities.md"
    # A run marked again reports only the judge's cost; the replies were paid for before.
    report = as_markdown(results, reply_model=reply_model, judge_model=judge_model, when=when.strftime("%d %B %Y, %H:%M"), cost_usd=cost)
    path.write_text(report + "\n", encoding="utf-8")
    path.with_suffix(".json").write_text(json.dumps(saved(results, reply_model=reply_model, when=when), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Report: {path}" + (" (marked again)" if marked_again else ""))
    print(f"Saved run: {path.with_suffix('.json')}")


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
