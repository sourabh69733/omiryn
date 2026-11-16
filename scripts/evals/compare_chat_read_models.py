#!/usr/bin/env python3
"""Write the read of one chat with several models and put the results side by side.

The counted half of a read is code and is the same for every model; this compares the written
half (headline, roles, running jokes, what they return to, where they bump, the good thing, the
roast) and what each model costs for it.

  # a made-up sample chat, with the usual model and three Claude models
  .venv/bin/python scripts/evals/compare_chat_read_models.py

  # your own WhatsApp export (the reads print in your terminal; nothing is stored)
  .venv/bin/python scripts/evals/compare_chat_read_models.py --file ~/Downloads/chat.txt --me "Your Name"

Claude models need ANTHROPIC_API_KEY in .env. Costs a few rupees a run. The result is also saved
under reports/evals/<date>/chat-read-models.md (reports/ is not in git).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
load_dotenv(PROJECT_ROOT / ".env")
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent.cognition.background.uploads.chat_read import (  # noqa: E402
    CHAT_READ_SCHEMA,
    CHAT_READ_SYSTEM_PROMPT,
    chat_counts,
    read_input,
    sample_lines,
    two_sides,
    validate_written,
)
from agent.observability.usage import CHAT_READ  # noqa: E402
from agent.providers import write_chat_read  # noqa: E402
from agent.providers.claude import ClaudeUnavailable, claude_json, is_claude  # noqa: E402
from ingestion.upload_chat import whatsapp_upload_messages  # noqa: E402

DEFAULT_MODELS = "default,claude-haiku-5-5,claude-sonnet-5-5,claude-opus-5-5"
USD_TO_INR = 88.0


async def _one(model: str, payload: str, shown: set[int]) -> dict:
    started = perf_counter()
    try:
        if is_claude(model):
            raw, usage = await claude_json(CHAT_READ_SYSTEM_PROMPT, payload, model=model, schema=CHAT_READ_SCHEMA, request_kind=CHAT_READ)
        else:
            raw = await write_chat_read(payload, conversation_id="", model=None if model == "default" else model)
            # The gateway logs its own usage; here only a rough size, four characters a token.
            usage = {"input_tokens": (len(CHAT_READ_SYSTEM_PROMPT) + len(payload)) // 4, "output_tokens": None, "cost_usd": None, "seconds": round(perf_counter() - started, 1)}
    except ClaudeUnavailable as error:
        return {"model": model, "error": str(error)}
    except Exception as error:  # one model failing must not lose the others
        return {"model": model, "error": type(error).__name__}
    written = validate_written(raw, shown)
    dropped = sum(len(raw.get(key) or []) - len(written[key]) for key in ("running_jokes", "keep_coming_back_to") if isinstance(raw.get(key), list))
    return {"model": model, "written": written, "usage": usage, "dropped": dropped}


def _show(result: dict, me: str, them: str) -> str:
    lines = [f"## {result['model']}", ""]
    if result.get("error"):
        return "\n".join(lines + [f"Failed: {result['error']}", ""])
    usage, written = result["usage"], result["written"]
    cost = usage.get("cost_usd")
    lines.append(
        f"{usage['seconds']} s · {usage['input_tokens']} tokens in"
        + (f" · {usage['output_tokens']} out" if usage.get("output_tokens") is not None else " (rough)")
        + (f" · ${cost:.4f}, about ₹{cost * USD_TO_INR:.2f}" if cost is not None else " · cost in the provider's own log")
        + (f" · {result['dropped']} item(s) dropped by the checks" if result["dropped"] else "")
    )
    lines += ["", f"**{written['headline']}**", "", written["you_two"], ""]
    lines.append(f"- {me}: {written['roles']['me']}")
    lines.append(f"- {them}: {written['roles']['them']}")
    lines.append("- Running jokes: " + ("; ".join(item["text"] for item in written["running_jokes"]) or "none"))
    lines.append("- Keep coming back to: " + ("; ".join(item["text"] for item in written["keep_coming_back_to"]) or "none"))
    lines.append("- Where they bump: " + (written["friction"]["text"] if written["friction"] else "none"))
    lines.append(f"- The good thing: {written['green_flag']}")
    lines.append(f"- The roast: {written['roast']}")
    return "\n".join(lines + [""])


async def _run(args: argparse.Namespace) -> int:
    zone = ZoneInfo(args.timezone)
    if args.file:
        export, me_name = Path(args.file).expanduser().read_text(encoding="utf-8", errors="replace"), args.me
        if not me_name:
            print("--file needs --me \"your name as it appears in the chat\"", file=sys.stderr)
            return 2
    else:
        from agent.evals.memory.upload_chats import EXPORT, USER

        export, me_name = EXPORT, USER
    messages, partner, others = two_sides(whatsapp_upload_messages(export, me_name, zone))
    if others != 1 or not partner:
        print("The read needs a chat between two people.", file=sys.stderr)
        return 2
    me, them = me_name.split()[0], partner.split()[0]
    counts = chat_counts(messages, zone)
    lines = sample_lines(messages, zone)
    payload = read_input(me, them, counts, lines)
    models = [model.strip() for model in args.models.split(",") if model.strip()]
    print(f"{len(messages)} messages, {len(lines)} lines shown to each model, models: {', '.join(models)}", flush=True)
    results = await asyncio.gather(*(_one(model, payload, {line["n"] for line in lines}) for model in models))
    text = "\n".join(_show(result, me, them) for result in results)
    print()
    print(text)
    if not args.no_save and not args.file:
        # Only the made-up sample is saved; a read of someone's own chat stays in their terminal.
        folder = PROJECT_ROOT / "reports" / "evals" / datetime.now().strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "chat-read-models.md").write_text(f"# The read, by model\n\n{datetime.now():%Y-%m-%d %H:%M} · made-up sample chat, {len(messages)} messages\n\n{text}\n", encoding="utf-8")
        print(f"saved reports/evals/{datetime.now():%Y-%m-%d}/chat-read-models.md")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", default=DEFAULT_MODELS, help=f"Comma-separated; \"default\" is the usual read model (default: {DEFAULT_MODELS}).")
    parser.add_argument("--file", default=None, help="A WhatsApp export (.txt) of a chat between two people.")
    parser.add_argument("--me", default=None, help="With --file: your name as it appears in the chat.")
    parser.add_argument("--timezone", default="Asia/Kolkata")
    parser.add_argument("--no-save", action="store_true")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
