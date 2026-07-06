from __future__ import annotations

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, MetaData, String, Table, func

DEFAULT_DATABASE_URL = "sqlite:///./data/omiryn.db"

# Vercel/serverless should not keep an application-side SQLAlchemy pool.
DB_DISABLE_POOL = "false"


# Vercel/serverless should not keep an application-side SQLAlchemy pool.
DB_DISABLE_POOL="false"

metadata = MetaData()

draft_profiles = Table(
    "draft_profiles",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=True),
    Column("status", String, nullable=False),
    Column("submission_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

agent_conversations = Table(
    "agent_conversations",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=True),
    Column("status", String, nullable=False),
    Column("agent_provider", String, nullable=True),
    Column("agent_model", String, nullable=True),
    Column("agent_mode", String, nullable=True),
    Column("agent_tone", String, nullable=True),
    Column("agent_name", String, nullable=True),
    Column("agent_style_source_id", String, nullable=True),
    Column("messages_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

agent_usage_events = Table(
    "agent_usage_events",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=True),
    Column("request_kind", String, nullable=False),
    Column("provider", String, nullable=False),
    Column("model", String, nullable=True),
    Column("success", Boolean, nullable=False),
    Column("prompt_tokens", Integer, nullable=True),
    Column("completion_tokens", Integer, nullable=True),
    Column("total_tokens", Integer, nullable=True),
    Column("latency_ms", Integer, nullable=True),
    Column("estimated_cost_usd", Float, nullable=True),
    Column("error", String, nullable=True),
    Column("raw_usage_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

agent_context_snapshots = Table(
    "agent_context_snapshots",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=False),
    Column("message_index", Integer, nullable=False),
    Column("summary_json", JSON, nullable=False),
    Column("context_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

agent_traces = Table(
    "agent_traces",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=False),
    Column("turn_index", Integer, nullable=False),
    Column("agent_mode", String, nullable=True),
    Column("agent_tone", String, nullable=True),
    Column("model", String, nullable=True),
    Column("status", String, nullable=False),
    Column("summary_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
)

agent_trace_steps = Table(
    "agent_trace_steps",
    metadata,
    Column("id", String, primary_key=True),
    Column("trace_id", String, nullable=False),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=False),
    Column("step_index", Integer, nullable=False),
    Column("step_name", String, nullable=False),
    Column("status", String, nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

agent_eval_runs = Table(
    "agent_eval_runs",
    metadata,
    Column("id", String, primary_key=True),
    Column("suite_name", String, nullable=False),
    Column("provider", String, nullable=False),
    Column("model", String, nullable=True),
    Column("status", String, nullable=False),
    Column("passed", Integer, nullable=False),
    Column("failed", Integer, nullable=False),
    Column("total", Integer, nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
)

agent_eval_case_results = Table(
    "agent_eval_case_results",
    metadata,
    Column("id", String, primary_key=True),
    Column("run_id", String, nullable=False),
    Column("case_id", String, nullable=False),
    Column("status", String, nullable=False),
    Column("failures_json", JSON, nullable=False),
    Column("expected_json", JSON, nullable=False),
    Column("observed_json", JSON, nullable=False),
    Column("trace_count", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

conversation_context_sources = Table(
    "conversation_context_sources",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=False),
    Column("source_type", String, nullable=False),
    Column("title", String, nullable=False),
    Column("content", String, nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

whatsapp_imports = Table(
    "whatsapp_imports",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=False),
    Column("context_source_id", String, nullable=False),
    Column("style_kind", String, nullable=False),
    Column("title", String, nullable=False),
    Column("selected_sender", String, nullable=True),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

whatsapp_messages = Table(
    "whatsapp_messages",
    metadata,
    Column("id", String, primary_key=True),
    Column("import_id", String, nullable=False),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=False),
    Column("message_index", Integer, nullable=False),
    Column("sender", String, nullable=False),
    Column("timestamp_text", String, nullable=True),
    Column("content", String, nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

whatsapp_chunks = Table(
    "whatsapp_chunks",
    metadata,
    Column("id", String, primary_key=True),
    Column("import_id", String, nullable=False),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=False),
    Column("chunk_index", Integer, nullable=False),
    Column("start_message_index", Integer, nullable=False),
    Column("end_message_index", Integer, nullable=False),
    Column("content", String, nullable=False),
    Column("terms_json", JSON, nullable=False),
    Column("embedding_json", JSON, nullable=True),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

whatsapp_people = Table(
    "whatsapp_people",
    metadata,
    Column("id", String, primary_key=True),
    Column("import_id", String, nullable=False),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=False),
    Column("sender", String, nullable=False),
    Column("message_count", Integer, nullable=False),
    Column("role", String, nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

whatsapp_style_profiles = Table(
    "whatsapp_style_profiles",
    metadata,
    Column("id", String, primary_key=True),
    Column("import_id", String, nullable=False),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=False),
    Column("sender", String, nullable=False),
    Column("summary_json", JSON, nullable=False),
    Column("sample_messages_json", JSON, nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

user_profiles = Table(
    "user_profiles",
    metadata,
    Column("user_id", String, primary_key=True),
    Column("display_name", String, nullable=True),
    Column("age", Integer, nullable=True),
    Column("gender", String, nullable=True),
    Column("interested_in", String, nullable=True),
    Column("city", String, nullable=True),
    Column("phone", String, nullable=True),
    Column("profile_photo_url", String, nullable=True),
    Column("profile_photo_urls", JSON, nullable=True),
    Column("profile_photo_file_name", String, nullable=True),
    Column("profile_photo_file_names", JSON, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

profile_facts = Table(
    "profile_facts",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("category", String, nullable=False),
    Column("key", String, nullable=False),
    Column("value_json", JSON, nullable=False),
    Column("label", String, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("source_kind", String, nullable=False),
    Column("source_id", String, nullable=True),
    Column("evidence_json", JSON, nullable=False),
    Column("status", String, nullable=False),
    Column("visibility", String, nullable=False),
    Column("used_for_matching", Boolean, nullable=False),
    Column("used_for_chat_context", Boolean, nullable=False, default=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

data_point_feedback = Table(
    "data_point_feedback",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("profile_fact_id", String, nullable=False),
    Column("rating", String, nullable=False),
    Column("reason", String, nullable=True),
    Column("comment", String, nullable=True),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

data_point_extraction_debug = Table(
    "data_point_extraction_debug",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=True),
    Column("source_kind", String, nullable=False),
    Column("source_id", String, nullable=True),
    Column("import_id", String, nullable=True),
    Column("candidate_key", String, nullable=True),
    Column("decision", String, nullable=False),
    Column("candidate_json", JSON, nullable=False),
    Column("review_json", JSON, nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

agent_message_feedback = Table(
    "agent_message_feedback",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=False),
    Column("message_index", Integer, nullable=False),
    Column("rating", String, nullable=False),
    Column("reason", String, nullable=True),
    Column("comment", String, nullable=True),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
