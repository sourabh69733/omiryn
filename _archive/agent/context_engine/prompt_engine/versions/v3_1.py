from __future__ import annotations

from dataclasses import replace

from agent.context_engine.prompt_engine.versions.v3 import V3_PROMPT_VERSION


# The first V3.1 slice intentionally preserves V3's prompt. Matching discovery will
# only influence replies after its derived progress has been verified independently.
V3_1_PROMPT_VERSION = replace(
    V3_PROMPT_VERSION,
    version_id="v3-1",
    name="v3_1_matching_discovery_companion",
)
