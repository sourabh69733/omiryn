"""Read a link the user pasted, before the draft, whichever model writes the reply.

A pasted link is a fact code can see, and a reply about a page nobody read is made up. So code reads
the page with the read_page tool (same address checks) and adds it to what the reply model reads,
as the result of a read made for it. The model keeps the tool and can read more, or read again for
one part of the page.

Best effort: a page that cannot be opened comes back as a note saying so, and any failure here
leaves the turn exactly as it would be without this step.
"""

from __future__ import annotations

import os
from dataclasses import replace
from time import perf_counter
from typing import Any

from agent.tools import ToolCall, ToolContext, links_in, read_page_enabled, tool_result_messages

from .job import ReplyJob

# A message with more links than this gets the first ones read; the model can read the rest.
MAX_LINKS = 2


def read_links_enabled() -> bool:
    """On when the page reader is on, unless AGENT_READ_PASTED_LINKS=false."""
    return read_page_enabled() and os.getenv("AGENT_READ_PASTED_LINKS", "true").strip().lower() != "false"


async def read_pasted_links(job: ReplyJob) -> tuple[ReplyJob, dict[str, Any] | None]:
    """(the job, with the pages added to what the reply model reads; trace facts or None).

    The trace holds counts and timings only, never an address or the page."""
    links = links_in(job.user_text)[:MAX_LINKS] if read_links_enabled() else []
    if not links:
        return job, None
    started = perf_counter()
    context = ToolContext(user_id=job.user_id, conversation_id=job.conversation_id, user_text=job.user_text)
    calls = [ToolCall("read_page", {"url": link}) for link in links]
    try:
        # Looked up at call time through the loop module, the one place tool calls are run from.
        from agent.tools import loop

        results = await loop.run_calls(calls, context)
    except Exception as error:
        return job, {"links": len(links), "error": type(error).__name__, "ms": int((perf_counter() - started) * 1000)}
    found = tool_result_messages(calls, results, step="link")
    info = {"links": len(links), "results": [result.trace for result in results], "ms": int((perf_counter() - started) * 1000)}
    # Part of the history from here on, so the draft, a tool round and any rewrite all read it.
    return replace(job, reply_messages=[*job.reply_messages, *found]), info


__all__ = ["read_links_enabled", "read_pasted_links"]
