from __future__ import annotations

from agent.context_engine.prompt_engine.models import PromptBehaviorVersion


def conversation_flow_prompt(prompt_version: PromptBehaviorVersion) -> str:
    flow = prompt_version.conversation_flow
    if not flow:
        return ""
    return (
        "Conversation flow config: "
        f"dry_reply_strategy={flow.get('dry_reply_strategy')}; "
        f"starter_strategy={flow.get('starter_strategy')}; "
        f"allow_imagined_scenes={flow.get('allow_imagined_scenes')}; "
        f"emotional_depth={flow.get('emotional_depth')}."
    )
