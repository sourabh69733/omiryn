CREATE TABLE IF NOT EXISTS feedback_submissions (
  response_id TEXT PRIMARY KEY,
  survey_version TEXT NOT NULL,
  client_token_hash TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  meeting_paths TEXT NOT NULL,
  compatibility_challenges TEXT NOT NULL,
  compatibility_signals TEXT NOT NULL,
  concept_usefulness TEXT NOT NULL,
  concept_concerns TEXT NOT NULL,
  must_get_right TEXT NOT NULL DEFAULT ''
);

-- One browser can submit once per survey version, while response_id protects
-- idempotent retries of the same network request.
CREATE UNIQUE INDEX IF NOT EXISTS ux_feedback_submissions_version_client
  ON feedback_submissions (survey_version, client_token_hash);

-- Keep the per-source hourly abuse query bounded without retaining raw IPs.
CREATE INDEX IF NOT EXISTS ix_feedback_submissions_source_received
  ON feedback_submissions (source_hash, received_at);
