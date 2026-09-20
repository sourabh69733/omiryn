from __future__ import annotations

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Index, Integer, MetaData, String, Table, func

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
    Column("user_id", String, nullable=False),
    Column("status", String, nullable=False),
    Column("submission_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

agent_conversations = Table(
    "agent_conversations",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
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

# One lightweight pointer per chat session. Detailed subjects live in the
# user-level conversation_threads table so they can continue across sessions.
conversation_states = Table(
    "conversation_states",
    metadata,
    Column("conversation_id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("state_through_message_index", Integer, nullable=False, default=-1),
    Column("active_thread_id", String, nullable=True),
    Column("user_need", String, nullable=False, default="normal_chat"),
    Column("session_goal", String, nullable=True),
    Column("version", Integer, nullable=False, default=1),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
Index("ix_conversation_states_user", conversation_states.c.user_id)

# Tracks background-memory progress independently from live conversation state.
# The encrypted handoff connects adjacent extraction batches without resending the
# complete conversation or treating overlap messages as new evidence.
memory_processing_states = Table(
    "memory_processing_states",
    metadata,
    Column("conversation_id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("processed_through_message_index", Integer, nullable=False, default=-1),
    Column("last_batch_key", String, nullable=True),
    Column("handoff_json", JSON, nullable=False),
    Column("version", Integer, nullable=False, default=1),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
Index("ix_memory_processing_states_user", memory_processing_states.c.user_id)

# Claims one bounded cognition batch before its model call. The expiring owner
# token prevents duplicate calls while allowing recovery after a crashed worker.
memory_processing_leases = Table(
    "memory_processing_leases",
    metadata,
    Column("batch_key", String, primary_key=True),
    Column("conversation_id", String, nullable=False),
    Column("user_id", String, nullable=False),
    Column("owner_token", String, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
Index("ix_memory_processing_leases_user", memory_processing_leases.c.user_id)
Index(
    "ix_memory_processing_leases_conversation",
    memory_processing_leases.c.conversation_id,
)

# Records each validated background-memory operation exactly once. Operation and
# snapshots may contain private evidence, so storage encrypts the JSON payloads.
memory_operation_applications = Table(
    "memory_operation_applications",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("conversation_id", String, nullable=False),
    Column("batch_key", String, nullable=False),
    Column("operation_index", Integer, nullable=False),
    Column("operation_fingerprint", String, nullable=False),
    Column("operation_kind", String, nullable=False),
    Column("outcome", String, nullable=False),
    Column("target_memory_id", String, nullable=True),
    Column("result_memory_id", String, nullable=True),
    Column("operation_json", JSON, nullable=False),
    Column("before_json", JSON, nullable=True),
    Column("after_json", JSON, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
Index(
    "uq_memory_operation_applications_batch_index",
    memory_operation_applications.c.user_id,
    memory_operation_applications.c.conversation_id,
    memory_operation_applications.c.batch_key,
    memory_operation_applications.c.operation_index,
    unique=True,
)
Index(
    "ix_memory_operation_applications_user_created",
    memory_operation_applications.c.user_id,
    memory_operation_applications.c.created_at,
)

# Canonical v3 durable memories. Working context and conversation threads remain
# separate systems because they have different lifecycles and retrieval rules.
agent_memories = Table(
    "agent_memories",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("purposes_json", JSON, nullable=False),
    Column("key", String, nullable=False),
    Column("value_json", JSON, nullable=False),
    Column("allowed_uses_json", JSON, nullable=False),
    Column("status", String, nullable=False),
    Column("sensitivity", String, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("importance", Float, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=True),
    Column("valid_from", DateTime(timezone=True), nullable=True),
    Column("valid_until", DateTime(timezone=True), nullable=True),
    Column("last_reinforced_at", DateTime(timezone=True), nullable=True),
    Column("supersedes_memory_id", String, nullable=True),
    Column("extractor", String, nullable=True),
    Column("extractor_model", String, nullable=True),
    Column("schema_version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
Index(
    "ix_agent_memories_user_status_kind_updated",
    agent_memories.c.user_id,
    agent_memories.c.status,
    agent_memories.c.kind,
    agent_memories.c.updated_at,
)

# Embeddings are stored separately from canonical memory content so models can be
# changed or re-indexed without rewriting the user's memory record.
agent_memory_embeddings = Table(
    "agent_memory_embeddings",
    metadata,
    Column("id", String, primary_key=True),
    Column("memory_id", String, nullable=False),
    Column("user_id", String, nullable=False),
    Column("provider", String, nullable=False),
    Column("model", String, nullable=False),
    Column("dimensions", Integer, nullable=False),
    Column("values_json", JSON, nullable=False),
    Column("content_hash", String, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
Index(
    "ix_agent_memory_embeddings_memory_model",
    agent_memory_embeddings.c.memory_id,
    agent_memory_embeddings.c.provider,
    agent_memory_embeddings.c.model,
    unique=True,
)
Index(
    "ix_agent_memory_embeddings_user_model",
    agent_memory_embeddings.c.user_id,
    agent_memory_embeddings.c.provider,
    agent_memory_embeddings.c.model,
)

# Evidence is normalized so one memory can be supported by messages from
# multiple conversations without duplicating the memory itself.
agent_memory_evidence = Table(
    "agent_memory_evidence",
    metadata,
    Column("id", String, primary_key=True),
    Column("memory_id", String, nullable=False),
    Column("user_id", String, nullable=False),
    Column("conversation_id", String, nullable=False),
    Column("message_id", String, nullable=True),
    Column("message_index", Integer, nullable=True),
    Column("exact_quote", String, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
Index("ix_agent_memory_evidence_memory", agent_memory_evidence.c.memory_id)
Index(
    "ix_agent_memory_evidence_conversation",
    agent_memory_evidence.c.user_id,
    agent_memory_evidence.c.conversation_id,
)

# User reviews are append-only so later corrections never erase earlier feedback.
agent_memory_reviews = Table(
    "agent_memory_reviews",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("memory_id", String, nullable=False),
    Column("rating", String, nullable=False),
    Column("reasons", JSON, nullable=False, default=list),
    Column("comment", String, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
Index(
    "ix_agent_memory_reviews_user_memory_created",
    agent_memory_reviews.c.user_id,
    agent_memory_reviews.c.memory_id,
    agent_memory_reviews.c.created_at,
)

# Threads represent resumable subjects, not classifications for every message.
# A thread is user-owned and records its first/last session so it may span chats.
conversation_threads = Table(
    "conversation_threads",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("created_in_conversation_id", String, nullable=False),
    Column("last_conversation_id", String, nullable=False),
    Column("title", String, nullable=False),
    Column("summary", String, nullable=False),
    Column("origin", String, nullable=False),
    Column("matching_dimension", String, nullable=True),
    Column("status", String, nullable=False, default="open"),
    Column("depth", String, nullable=False, default="mentioned"),
    Column("user_interest", String, nullable=False, default="unknown"),
    Column("salience", Float, nullable=False, default=0.5),
    Column("next_angle", String, nullable=True),
    Column("first_message_index", Integer, nullable=True),
    Column("last_message_index", Integer, nullable=True),
    Column("closure_reason", String, nullable=True),
    Column("version", Integer, nullable=False, default=1),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
Index(
    "ix_conversation_threads_user_status_updated",
    conversation_threads.c.user_id,
    conversation_threads.c.status,
    conversation_threads.c.updated_at,
)
Index(
    "ix_conversation_threads_last_conversation",
    conversation_threads.c.last_conversation_id,
)

# Records one validated background thread operation exactly once per batch.
thread_operation_applications = Table(
    "thread_operation_applications",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("conversation_id", String, nullable=False),
    Column("batch_key", String, nullable=False),
    Column("operation_fingerprint", String, nullable=False),
    Column("operation_kind", String, nullable=False),
    Column("thread_id", String, nullable=True),
    Column("operation_json", JSON, nullable=False),
    Column("result_json", JSON, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
Index(
    "uq_thread_operation_applications_batch",
    thread_operation_applications.c.user_id,
    thread_operation_applications.c.conversation_id,
    thread_operation_applications.c.batch_key,
    unique=True,
)
Index(
    "ix_thread_operation_applications_user_created",
    thread_operation_applications.c.user_id,
    thread_operation_applications.c.created_at,
)

agent_usage_events = Table(
    "agent_usage_events",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
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

public_events = Table(
    "public_events",
    metadata,
    Column("id", String, primary_key=True),
    Column("session_id", String, nullable=False),
    Column("event_name", String, nullable=False),
    Column("path", String, nullable=False),
    Column("referrer", String, nullable=True),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

public_leads = Table(
    "public_leads",
    metadata,
    Column("id", String, primary_key=True),
    Column("session_id", String, nullable=True),
    Column("name", String, nullable=True),
    Column("contact", String, nullable=False),
    Column("channel", String, nullable=False),
    Column("intent", String, nullable=False),
    Column("message", String, nullable=True),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

data_requests = Table(
    "data_requests",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("email", String, nullable=True),
    Column("request_type", String, nullable=False),
    Column("status", String, nullable=False),
    Column("message", String, nullable=True),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

app_events = Table(
    "app_events",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("session_id", String, nullable=True),
    Column("event_name", String, nullable=False),
    Column("page", String, nullable=True),
    Column("target_type", String, nullable=True),
    Column("target_id", String, nullable=True),
    Column("metadata_json", JSON, nullable=False),
    Column("client_created_at", String, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
# Quota queries use this left-to-right key order, followed by a created_at range.
Index(
    "ix_app_events_user_event_created_at",
    app_events.c.user_id,
    app_events.c.event_name,
    app_events.c.created_at,
)

feedback_submissions = Table(
    "feedback_submissions",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("email", String, nullable=True),
    Column("category", String, nullable=False),
    Column("message", String, nullable=False),
    Column("allow_contact", Boolean, nullable=False),
    Column("status", String, nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

agent_context_snapshots = Table(
    "agent_context_snapshots",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
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
    Column("user_id", String, nullable=False),
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
    Column("user_id", String, nullable=False),
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
    Column("user_id", String, nullable=False),
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
    Column("user_id", String, nullable=False),
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
    Column("user_id", String, nullable=False),
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
    Column("user_id", String, nullable=False),
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
    Column("user_id", String, nullable=False),
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
    Column("user_id", String, nullable=False),
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

agent_user_settings = Table(
    "agent_user_settings",
    metadata,
    Column("user_id", String, primary_key=True),
    Column("proactive_enabled", Boolean, nullable=False, default=True),
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
    Column("fact_type", String, nullable=False, default="matching_fact"),
    Column("confidence_state", String, nullable=False, default="active"),
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

agent_behavior_rules = Table(
    "agent_behavior_rules",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("category", String, nullable=False),
    Column("key", String, nullable=False),
    Column("rule_text", String, nullable=False),
    Column("avoid_text", String, nullable=True),
    Column("prefer_text", String, nullable=True),
    Column("confidence", Float, nullable=False),
    Column("priority", Integer, nullable=False),
    Column("source_kind", String, nullable=False),
    Column("source_id", String, nullable=True),
    Column("evidence_json", JSON, nullable=False),
    Column("status", String, nullable=False),
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
    Column("user_id", String, nullable=False),
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
    Column("user_id", String, nullable=False),
    Column("conversation_id", String, nullable=False),
    Column("message_index", Integer, nullable=False),
    Column("rating", String, nullable=False),
    Column("reason", String, nullable=True),
    Column("comment", String, nullable=True),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
