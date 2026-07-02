from __future__ import annotations

from dataclasses import replace

from agent.context_engine.prompt_engine.versions.v1 import V1_PROMPT_VERSION


V2_PROMPT_VERSION = replace(
    V1_PROMPT_VERSION,
    version_id="v2",
    name="v2_story_companion_draft",
    prompt_contract="""Internal prompt behavior version: v2_story_companion_draft.
Draft only. Use v1 behavior unless this version is explicitly enabled.
Future goal: add controlled conversation starters and small fictional social scenes
without pretending invented scenes are the user's memories.""",
    conversation_flow={
        **V1_PROMPT_VERSION.conversation_flow,
        "starter_strategy": "story_companion_draft",
        "allow_imagined_scenes": True,
    },
)
