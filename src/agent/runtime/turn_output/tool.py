from __future__ import annotations


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
                            "or useful temporary context. Do not infer beyond what was stated."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "description": (
                                        "profile_fact describes the user; matching_fact affects "
                                        "compatibility or partner preferences; chat_learning "
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
                                        "not add inferred or normalized values that the user did not say."
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
