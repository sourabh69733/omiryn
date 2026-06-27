from __future__ import annotations


CHAT_REPLY = "chat_reply"
INPUT_GUARDRAIL = "input_guardrail"
PROFILE_EXTRACT = "profile_extract"
PROFILE_EXTRACT_REPAIR = "profile_extract_repair"
PROFILE_FACT_EXTRACT = "profile_fact_extract"
DATA_POINT_EXTRACT = "data_point_extract"

PROFILE_SIGNAL_EXTRACT = "profile_signal_extract"
PROFILE_SIGNAL_BACKFILL = "profile_signal_backfill"
PROFILE_FACT_AGGREGATE = "profile_fact_aggregate"
MATCH_SNAPSHOT_GENERATE = "match_snapshot_generate"

PROFILE_INTELLIGENCE_REQUEST_KINDS = {
    PROFILE_SIGNAL_EXTRACT,
    PROFILE_SIGNAL_BACKFILL,
    PROFILE_FACT_AGGREGATE,
    MATCH_SNAPSHOT_GENERATE,
}
