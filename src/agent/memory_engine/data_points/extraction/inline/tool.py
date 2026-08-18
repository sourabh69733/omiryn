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
                "additionalProperties": False,
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
                            "additionalProperties": False,
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


_OPTIONAL_TEXT = {"type": ["string", "null"]}
_OPTIONAL_DEPTH = {
    "type": ["string", "null"],
    "enum": ["mentioned", "explored", "meaningful", None],
}
_OPTIONAL_INTEREST = {
    "type": ["string", "null"],
    "enum": ["unknown", "low", "medium", "high", None],
}
_OPTIONAL_SALIENCE = {
    "type": ["number", "null"],
    "minimum": 0,
    "maximum": 1,
}


def _existing_thread_action_schema(
    operation: str,
    description: str,
    *,
    mutable_fields: tuple[str, ...],
) -> dict[str, Any]:
    optional_properties = {
        "title": _OPTIONAL_TEXT,
        "summary": _OPTIONAL_TEXT,
        "matching_dimension": _OPTIONAL_TEXT,
        "depth": _OPTIONAL_DEPTH,
        "user_interest": _OPTIONAL_INTEREST,
        "salience": _OPTIONAL_SALIENCE,
        "next_angle": _OPTIONAL_TEXT,
        "closure_reason": _OPTIONAL_TEXT,
    }
    return {
        "type": "object",
        "description": description,
        "additionalProperties": False,
        "properties": {
            "operation": {"const": operation},
            "thread_id": {
                "type": "string",
                "description": "Select an existing thread_id supplied in conversation context.",
            },
            **{field: optional_properties[field] for field in mutable_fields},
        },
        "required": ["operation", "thread_id"],
    }


THREAD_ACTION_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "description": (
                "No durable thread action. Use for greetings, acknowledgements, jokes, "
                "isolated small talk, or a message that does not change a resumable subject."
            ),
            "additionalProperties": False,
            "properties": {"operation": {"const": "none"}},
            "required": ["operation"],
        },
        {
            "type": "object",
            "description": "Create one new meaningful, resumable subject introduced this turn.",
            "additionalProperties": False,
            "properties": {
                "operation": {"const": "create"},
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "origin": {
                    "type": "string",
                    "enum": ["user_started", "agent_started"],
                },
                "matching_dimension": _OPTIONAL_TEXT,
                "depth": _OPTIONAL_DEPTH,
                "user_interest": _OPTIONAL_INTEREST,
                "salience": _OPTIONAL_SALIENCE,
                "next_angle": _OPTIONAL_TEXT,
            },
            "required": ["operation", "title", "summary", "origin"],
        },
        _existing_thread_action_schema(
            "continue",
            "Continue the currently active thread because the latest message develops it.",
            mutable_fields=(
                "title",
                "summary",
                "matching_dimension",
                "depth",
                "user_interest",
                "salience",
                "next_angle",
            ),
        ),
        _existing_thread_action_schema(
            "switch",
            "Switch from the active subject to a different existing open thread.",
            mutable_fields=(
                "title",
                "summary",
                "matching_dimension",
                "depth",
                "user_interest",
                "salience",
                "next_angle",
            ),
        ),
        _existing_thread_action_schema(
            "pause",
            "Pause an unfinished thread now while allowing it to be resumed later.",
            mutable_fields=("summary", "next_angle", "closure_reason"),
        ),
        _existing_thread_action_schema(
            "complete",
            "Complete a thread whose subject is resolved or explicitly finished.",
            mutable_fields=("summary", "closure_reason"),
        ),
        _existing_thread_action_schema(
            "block",
            "Block a thread when the user explicitly forbids returning to its subject.",
            mutable_fields=("summary", "closure_reason"),
        ),
    ]
}


CONVERSATION_UPDATE_SCHEMA = {
    "type": "object",
    "description": (
        "Private shadow proposal for meaningful, resumable conversation threads. "
        "Return one explicit none action when no thread changes. This proposal is never "
        "shown to the user."
    ),
    "additionalProperties": False,
    "properties": {
        "user_need": {
            "type": "string",
            "enum": ["normal_chat", "listen", "answer", "explore", "play", "space"],
        },
        "session_goal": {"type": ["string", "null"]},
        "thread_updates": {
            "type": "array",
            "description": (
                "Thread actions proposed for this turn. Use exactly one none action when no "
                "durable subject changes; never combine none with another action."
            ),
            "minItems": 1,
            "maxItems": 3,
            "items": THREAD_ACTION_SCHEMA,
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
