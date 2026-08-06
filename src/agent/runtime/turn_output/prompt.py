from __future__ import annotations


TURN_OUTPUT_V2_INSTRUCTION = """

Return ONLY one JSON object with this shape:
{"reply":"visible user-facing reply","data_points":[]}

data_points is for hidden memory candidates from the user's latest message only.
Use [] unless the user clearly reveals a useful profile, matching, chat-learning, or temporary context signal.
Each data point must have: type, category, label, value, evidence, confidence.
Allowed type values: profile_fact, matching_fact, chat_learning, temporary_context, needs_confirmation, do_not_store.
Evidence must be exact text written by the user, not your reply.
Do not mention data_points or JSON to the user inside reply.
""".strip()


def with_turn_output_v2_instruction(system_prompt: str) -> str:
    if TURN_OUTPUT_V2_INSTRUCTION in system_prompt:
        return system_prompt
    return f"{system_prompt.rstrip()}\n\n{TURN_OUTPUT_V2_INSTRUCTION}"
