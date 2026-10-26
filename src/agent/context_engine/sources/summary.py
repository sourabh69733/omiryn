"""The background-written summary of this chat, for parts beyond the recent messages."""

from __future__ import annotations

from typing import Any

from agent.config import agent_pipeline_config
from agent.memory_engine.processing.service import get_processing_state

# Procedural memories (how the user wants to be talked to) get their own source, kept apart
# from facts so the reply prompt can place them where they are followed (HOW_TO_TALK_SOURCE_TYPE).
CONVERSATION_SUMMARY_SOURCE_TYPE = "conversation_summary"


def conversation_summary_sources(
    conversation_id: str,
    user_id: str | None,
) -> list[dict[str, Any]]:
    """The background-written summary of this chat, for parts beyond the recent messages."""
    if not user_id or agent_pipeline_config().memory_contract_version != 3:
        return []
    state = get_processing_state(conversation_id, user_id)
    summary = state.handoff.conversation_summary if state else ""
    if not summary:
        return []
    return [
        {
            "source_type": CONVERSATION_SUMMARY_SOURCE_TYPE,
            "title": "Earlier in this chat",
            "content": (
                "Summary of older parts of this conversation. The recent messages are more "
                "exact; trust them when they differ.\n" + summary
            ),
            "metadata": {"processed_through_message_index": state.processed_through_message_index},
        }
    ]


__all__ = ["CONVERSATION_SUMMARY_SOURCE_TYPE", "conversation_summary_sources"]
