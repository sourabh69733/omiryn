"""When a draft says Omi does not know, search the real lines once before sending that."""

from __future__ import annotations

import json
from typing import Any

from agent.memory_engine.memories.embeddings import memory_query_text
from agent.memory_engine.search import search_chats_hybrid, search_note
from agent.memory_engine.search.chat_search import merge_hits, without_companion_lines
from agent.providers import write_search_queries
from agent.tools import ToolCall, ToolResult, tool_result_messages
from storage.upload_digests import list_upload_digests

from .job import ReplyJob

# The current chat's newest messages are skipped: the draft already saw them.
SKIP_RECENT = 30


async def search_when_unsure(draft: str, job: ReplyJob, *, extra_queries: list[str] | None = None) -> tuple[str, dict[str, Any] | None]:
    """Searches the question plus the written searches; only the user's or the other person's
    lines can match, so Omi's own earlier "I don't know" never counts. Returns the raw reply. When
    nothing is found, the honest draft stands."""
    query = memory_query_text(job.user_text, job.history)
    if extra_queries is None:
        extra_queries = await search_queries(job)
    skip = (job.conversation_id, max(0, len(job.history) - SKIP_RECENT))
    try:
        found = [
            await search_chats_hybrid(str(job.user_id), text[:300], limit=4, skip=skip, match_roles={"user", "other"})
            for text in [*extra_queries, query]
        ]
        hits = without_companion_lines(merge_hits(found, 6))
    except Exception as error:
        return draft, {"tool": "unsure_search", "error": type(error).__name__}
    if not hits:
        return draft, {"tool": "unsure_search", "query": query[:120], "hits": 0}
    # The lines come back as the result of a search_chats call made for the model, so what people
    # wrote in those chats is data it reads, not a system instruction.
    found_messages = tool_result_messages(
        [ToolCall("search_chats", {"query": query[:120]})],
        [ToolResult(search_note(query[:120], None, None, hits))],
        round_number=0,
    )
    note = {"role": "system", "content": "Your draft said you don't know; check the lines the search found first and answer from them if they do."}
    reply = await job.generate([*job.reply_messages, *found_messages, note], **job.generation_arguments)
    return reply, {"tool": "unsure_search", "query": query[:120], "queries": extra_queries, "hits": len(hits)}


async def search_queries(job: ReplyJob) -> list[str]:
    """Searches written by a fast model: the words the answer would use ("relationship status" ->
    engaged, shaadi, boyfriend). Empty when it fails; the plain question is searched anyway."""
    from agent.cognition.background.uploads.read import upload_model

    people = [stored["partner_name"] for stored in list_upload_digests(str(job.user_id)) if stored["partner_name"]]
    recent = [f'{m.get("role")}: {str(m.get("content") or "")[:200]}' for m in job.history[-4:]]
    try:
        raw = await write_search_queries(
            json.dumps({"question": job.user_text, "recent": recent, "people": people}, ensure_ascii=False),
            conversation_id=job.conversation_id,
            model=upload_model(),
        )
    except Exception:
        return []
    queries = raw.get("queries") if isinstance(raw, dict) else None
    return [query.strip()[:60] for query in queries or [] if isinstance(query, str) and query.strip()][:4]


__all__ = ["search_queries", "search_when_unsure"]
