"""V4.5: Omi knows who made it and what is in the app.

On V4.4, asked "who made you?", the model answered for itself: "made by the Omiryn team" and "not
made by Google", which is not true; another time it said "developed by Google". Asked how to do
something in the app, it guessed. V4.5 adds two fact blocks (see `modules/omiryn_facts.py`): who
made Omi, honest but general (Omiryn, on an AI model from another company, never named), and the
app's pages. A reply check in code rewrites any sentence that still names the maker. V4.4 stays for
rollback.
"""

from __future__ import annotations

from dataclasses import replace

from agent.context_engine.prompt_engine.versions.v4_4 import V4_4_PROMPT_VERSION

V4_5_PROMPT_VERSION = replace(
    V4_4_PROMPT_VERSION,
    version_id="v4-5",
    name="v4_5_knows_itself",
    knows_itself=True,
)
