"""Defines the provider-neutral schema for reply plus inline data-point candidates."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


TURN_OUTPUT_V2_TOOL_NAME = "return_companion_response"

TURN_OUTPUT_V2_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": TURN_OUTPUT_V2_TOOL_NAME,
            "description": (
                "Return the visible companion reply and private data-point candidates "
                "derived from the user's latest message. Inspect that message for candidates "
                "before returning the reply."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reply": {
                        "type": "string",
                        "description": "The natural user-facing chat reply.",
                    },
                    "data_points": {
                        "type": "array",
                        "description": (
                            "Include every clearly stated, useful signal from the latest user "
                            "message. Use an empty array only when that message reveals no "
                            "personal fact, compatibility preference, conversation learning, "
                            "or useful temporary context. Do not infer beyond what was stated. "
                            "When the user corrects an earlier point, reuse its semantic category "
                            "and key and represent only the latest explicit meaning. Never turn "
                            "removal of a preference into an opposite preference."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "description": (
                                        "profile_fact is only a stable identity or logistics fact "
                                        "such as age, location, language, education, or occupation. "
                                        "matching_fact covers all tastes, interests, preferences, "
                                        "values, lifestyle signals, boundaries, relationship intent, "
                                        "or partner preferences. chat_learning "
                                        "describes how to converse with the user; temporary_context "
                                        "is short-lived; needs_confirmation is useful but unclear; "
                                        "do_not_store marks information the user does not want saved."
                                    ),
                                    "enum": [
                                        "profile_fact",
                                        "matching_fact",
                                        "chat_learning",
                                        "temporary_context",
                                        "needs_confirmation",
                                        "do_not_store",
                                    ],
                                },
                                "category": {"type": "string"},
                                "label": {
                                    "type": "string",
                                    "description": (
                                        "A concrete, literal description of what the user revealed."
                                    ),
                                },
                                "value": {
                                    "description": (
                                        "Structured useful details. Preserve explicit names, places, "
                                        "items, and preferences using the exact words from the latest "
                                        "user message. Use arrays when several values are stated. Do "
                                        "not add inferred or normalized values that the user did not say. "
                                        "For a correction, store the corrected meaning itself—not the "
                                        "old value and not an invented opposite."
                                    )
                                },
                                "confidence": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                            },
                            "required": ["type", "category", "label", "value", "confidence"],
                        },
                    },
                },
                "required": ["reply", "data_points"],
            },
        },
    }
]

TURN_OUTPUT_V2_TOOL_CHOICE = {
    "type": "function",
    "function": {"name": TURN_OUTPUT_V2_TOOL_NAME},
}


CONVERSATION_UPDATE_SCHEMA = {
    "type": "object",
    "description": (
        "Private shadow proposal for meaningful, resumable conversation threads. "
        "Do not create a thread for greetings, jokes, acknowledgements, or isolated "
        "small talk. This proposal is never shown to the user."
    ),
    "properties": {
        "user_need": {
            "type": "string",
            "enum": ["normal_chat", "listen", "answer", "explore", "play", "space"],
        },
        "session_goal": {"type": ["string", "null"]},
        "thread_updates": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["create", "continue", "switch", "pause", "complete", "block"],
                    },
                    "thread_id": {"type": ["string", "null"]},
                    "title": {"type": ["string", "null"]},
                    "summary": {"type": ["string", "null"]},
                    "origin": {
                        "type": ["string", "null"],
                        "enum": ["user_started", "agent_started", None],
                    },
                    "matching_dimension": {"type": ["string", "null"]},
                    "depth": {
                        "type": ["string", "null"],
                        "enum": ["mentioned", "explored", "meaningful", None],
                    },
                    "user_interest": {
                        "type": ["string", "null"],
                        "enum": ["unknown", "low", "medium", "high", None],
                    },
                    "salience": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
                    "next_angle": {"type": ["string", "null"]},
                    "closure_reason": {"type": ["string", "null"]},
                },
                "required": ["operation"],
            },
        },
    },
    "required": ["user_need", "thread_updates"],
}


def turn_output_v2_tools(*, include_conversation_update: bool = False) -> list[dict[str, Any]]:
    """Return an isolated schema so optional additions never mutate the baseline."""
    tools = deepcopy(TURN_OUTPUT_V2_TOOLS)
    if not include_conversation_update:
        return tools
    tools[0]["function"]["description"] += (
        " Also return a private conversation-thread update proposal for shadow evaluation."
    )
    parameters = tools[0]["function"]["parameters"]
    parameters["properties"]["conversation_update"] = deepcopy(CONVERSATION_UPDATE_SCHEMA)
    parameters["required"].append("conversation_update")
    return tools
