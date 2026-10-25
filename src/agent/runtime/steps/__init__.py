"""The steps of one reply, in order:

1. notes: per-turn notes after the user's message (story, no questions, several messages at once).
2. draft: the reply model with tools; a search when it says it does not know; fallbacks.
3. checks: freshness (repeats, stock lines, too many questions), then how the user asked to be talked to.
4. finish: hidden markers out, the reply split into bubbles.

Every step gets the same ReplyJob, which carries the history and how to call the model.
"""

from .checks import REPLY_CHECKS, follow_requests, freshen_reply, freshness_check_enabled, request_check_enabled
from .draft import Draft, write_draft
from .finish import FinishedReply, assistant_messages, finish_reply
from .job import Generate, ReplyJob
from .notes import turn_notes
from .unsure_search import search_queries, search_when_unsure
from .visible import looks_like_model_transport, visible_reply

__all__ = [
    "REPLY_CHECKS",
    "Draft",
    "FinishedReply",
    "Generate",
    "ReplyJob",
    "assistant_messages",
    "finish_reply",
    "follow_requests",
    "freshen_reply",
    "freshness_check_enabled",
    "looks_like_model_transport",
    "request_check_enabled",
    "search_queries",
    "search_when_unsure",
    "turn_notes",
    "visible_reply",
    "write_draft",
]
