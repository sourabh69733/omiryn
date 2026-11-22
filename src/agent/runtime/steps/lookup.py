"""Look up fresh facts before the draft, whichever model writes the reply.

A small fast model reads the user's message and says whether the answer needs facts from the web,
and writes the searches. Code runs them through the web_search tool, so the same privacy guard,
country and date apply, and adds what they found to what the reply model reads, as the results of
a search made for it. The reply model keeps its tools and may search more.

Best effort: when the plan or a search fails, the turn goes on exactly as it would without this step.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from time import perf_counter
from typing import Any

from agent.context_engine.policy.lookup import lookup_plan_input, planned_searches
from agent.providers import plan_lookup
from agent.providers.shared.messages import _is_greeting_only
from agent.tools import ToolCall, ToolContext, tool_result_messages, web_search_enabled
from agent.tools.web_search import user_today

from .job import ReplyJob

# The plan is small; a slow one is dropped so a chat reply never waits long for it.
PLAN_TIMEOUT_SECONDS = 8.0


def lookup_step_enabled() -> bool:
    """Off unless AGENT_LOOKUP_STEP=true, and only with web search on.

    Off by default since the first measurement (2026-11-23, 41 career questions on Gemma): the
    plan asked the right searches, but it also searched on 14 questions that needed none, each
    turn waited about 2 seconds for the plan, and replies got worse, not better (17 right to 10).
    Kept to try again once the plan is strict enough and results are easier for a model to read."""
    return web_search_enabled() and os.getenv("AGENT_LOOKUP_STEP", "false").strip().lower() == "true"


async def look_up(job: ReplyJob, *, place: str | None = None) -> tuple[ReplyJob, dict[str, Any] | None]:
    """(the job, with what was found added to what the reply model reads; trace facts or None).

    The trace holds counts and timings only, never the message or the queries."""
    if not lookup_step_enabled() or not job.user_text.strip() or _is_greeting_only(job.user_text):
        return job, None
    started = perf_counter()
    context = ToolContext(user_id=job.user_id, conversation_id=job.conversation_id, user_text=job.user_text)
    try:
        raw = await asyncio.wait_for(
            plan_lookup(
                lookup_plan_input(job.user_text, job.history, today=user_today(context), place=place),
                conversation_id=job.conversation_id,
            ),
            PLAN_TIMEOUT_SECONDS,
        )
    except Exception as error:
        return job, {"planned": False, "error": type(error).__name__, "ms": _ms(started)}
    searches = planned_searches(raw)
    if not searches:
        return job, {"planned": True, "searches": 0, "ms": _ms(started)}
    calls = [ToolCall("web_search", search.arguments) for search in searches]
    try:
        # Looked up at call time through the loop module, the one place tool calls are run from.
        from agent.tools import loop

        results = await loop.run_calls(calls, context)
    except Exception as error:
        return job, {"planned": True, "searches": len(calls), "error": type(error).__name__, "ms": _ms(started)}
    found = tool_result_messages(calls, results, step="lookup")
    info = {
        "planned": True,
        "searches": len(calls),
        "results": [result.trace for result in results],
        "ms": _ms(started),
    }
    # Part of the history from here on, so the draft, a tool round and any rewrite all read it.
    return replace(job, reply_messages=[*job.reply_messages, *found]), info


def _ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


__all__ = ["look_up", "lookup_step_enabled"]
